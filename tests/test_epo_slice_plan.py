"""plans/patentmcp_bulk-entry-unification Phase 7 (DD-8/DD-9): epo_slice_plan.

Auto date-slicing planner tests. No real network — a Fake EPO client parses the
CQL `pd within "FROM TO"` window and returns a controllable `total` for that
date interval. Covers: single slice / recursive bisection to all-leaves<wall
(issue_20260710 shape: parent 22622, year-slices all >2000 → need finer split) /
DATE_RANGE_REQUIRED / SLICE_INEFFECTIVE / depth-cap truncated / probe-cap /
mutually-exclusive cut points / gpss+slice_plan → INVALID_PARAMS.

Run: uv run pytest tests/test_epo_slice_plan.py -q
"""
import asyncio
import os
import re
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import patent_mcp_server.patents as P
import patent_mcp_server.search_dispatcher as SD


def _run(coro):
    return asyncio.run(coro)


def _ymd(v):
    return date(int(v[0:4]), int(v[4:6]), int(v[6:8]))


def _days_inclusive(df, dt):
    return (_ymd(dt) - _ymd(df)).days + 1


# ── Fake EPO: total is a deterministic function of the pd window ─────
# A constant daily density makes bisection conserve exactly (leaf-sum == parent),
# which is the honest baseline the sum_check must accept.
class FakeEPO:
    """total = ceil(covered_days * density). Records the exact pd windows probed
    so tests can assert mutual-exclusivity of cut points."""

    def __init__(self, configured=True, density=None, total_fn=None):
        self._configured = configured
        self.density = density
        self.total_fn = total_fn
        self.search_calls = 0
        self.windows = []  # list of (date_from, date_to) parsed from each CQL
        self.ranges = []

    def configured(self):
        return self._configured

    async def search(self, cql, range_="1-1"):
        self.search_calls += 1
        self.ranges.append(range_)
        m = re.search(r'pd within "(\d{8}) (\d{8})"', cql)
        df, dt = (m.group(1), m.group(2)) if m else (None, None)
        self.windows.append((df, dt))
        if self.total_fn is not None:
            total = self.total_fn(df, dt)
        elif df and dt:
            days = _days_inclusive(df, dt)
            total = int(days * self.density)
        else:
            total = 0
        return {"success": True, "cql": cql, "total": total,
                "count": 0, "results": []}


def _with_clients(epo):
    orig = (P.gpss_client, P.epo_client, P._pdb)
    P.epo_client = epo  # type: ignore
    return orig


def _restore(orig):
    P.gpss_client, P.epo_client, P._pdb = orig  # type: ignore


# ── single slice: total ≤ wall → one slice, no bisection ─────────────
class SingleSlice(unittest.TestCase):
    def test_total_under_wall_single_slice(self):
        # 100 days * 5/day = 500 ≤ 2000
        epo = FakeEPO(density=5.0)
        spec = SD.normalize_query(keyword="radar", date_from="20200101",
                                  date_to="20200410")
        out = _run(SD.epo_slice_plan(spec, epo_client=epo))
        self.assertTrue(out["success"])
        self.assertEqual(len(out["slices"]), 1)
        self.assertEqual(out["slices"][0]["date_from"], "20200101")
        self.assertEqual(out["slices"][0]["date_to"], "20200410")
        self.assertLess(out["slices"][0]["total"], SD._EPO_SKIP_WALL)
        self.assertEqual(out["probe_calls"], 1)  # only the parent probe
        self.assertTrue(out["sum_check"]["ok"])

    def test_no_date_under_wall_single_slice(self):
        # no date range but total ≤ wall → single slice, no DATE_RANGE_REQUIRED
        epo = FakeEPO(total_fn=lambda df, dt: 1500)
        spec = SD.normalize_query(keyword="radar")
        out = _run(SD.epo_slice_plan(spec, epo_client=epo))
        self.assertTrue(out["success"])
        self.assertEqual(len(out["slices"]), 1)
        self.assertIsNone(out["slices"][0]["date_from"])


# ── recursive bisection to all leaves < wall (issue_20260710 shape) ──
class RecursiveBisection(unittest.TestCase):
    def test_year_slices_all_over_wall_need_finer_split(self):
        # issue shape: 10-year span (2015-2024), parent 22622. Year slices all
        # >2000 so the planner must bisect deeper. density ≈ 22622/3653 ≈ 6.19/day
        parent_days = _days_inclusive("20150101", "20241231")
        density = 22622.0 / parent_days
        epo = FakeEPO(density=density)
        spec = SD.normalize_query(keyword="radar AND fall",
                                  date_from="20150101", date_to="20241231")
        out = _run(SD.epo_slice_plan(spec, epo_client=epo))
        self.assertTrue(out["success"], out.get("message"))
        self.assertGreater(out["total"], SD._EPO_SKIP_WALL)
        # every leaf slice under the wall (none truncated at this density/span)
        for s in out["slices"]:
            self.assertLess(s["total"], SD._EPO_SKIP_WALL,
                            f"leaf {s} exceeds wall")
            self.assertNotIn("truncated", s)
        # conservation holds (constant density → exact)
        self.assertTrue(out["sum_check"]["ok"])
        self.assertLessEqual(
            abs(out["sum_check"]["sum"] - out["total"]),
            SD._EPO_SLICE_SUM_TOL * out["total"])

    def test_mutually_exclusive_cut_points(self):
        # adjacent leaves must not overlap: next.from == prev.to + 1 day
        density = 22622.0 / _days_inclusive("20150101", "20241231")
        epo = FakeEPO(density=density)
        spec = SD.normalize_query(keyword="radar",
                                  date_from="20150101", date_to="20241231")
        out = _run(SD.epo_slice_plan(spec, epo_client=epo))
        self.assertTrue(out["success"])
        slices = sorted(out["slices"], key=lambda s: s["date_from"])
        for prev, nxt in zip(slices, slices[1:]):
            gap = (_ymd(nxt["date_from"]) - _ymd(prev["date_to"])).days
            self.assertEqual(gap, 1,
                             f"overlap/gap between {prev} and {nxt}")
        # leaves tile the full parent span end-to-end
        self.assertEqual(slices[0]["date_from"], "20150101")
        self.assertEqual(slices[-1]["date_to"], "20241231")


# ── DATE_RANGE_REQUIRED: over wall, no date range → fail-fast ────────
class DateRangeRequired(unittest.TestCase):
    def test_over_wall_no_date_fail_fast(self):
        epo = FakeEPO(total_fn=lambda df, dt: 22622)
        spec = SD.normalize_query(keyword="radar")  # no date_from/date_to
        out = _run(SD.epo_slice_plan(spec, epo_client=epo))
        self.assertFalse(out["success"])
        self.assertEqual(out["error_code"], "DATE_RANGE_REQUIRED")
        self.assertEqual(epo.search_calls, 1)  # only the parent probe fired

    def test_over_wall_only_one_bound_fail_fast(self):
        # only date_from → still no closed range to bisect
        epo = FakeEPO(total_fn=lambda df, dt: 22622)
        spec = SD.normalize_query(keyword="radar", date_from="20150101")
        out = _run(SD.epo_slice_plan(spec, epo_client=epo))
        self.assertFalse(out["success"])
        self.assertEqual(out["error_code"], "DATE_RANGE_REQUIRED")


# ── SLICE_INEFFECTIVE: leaf-sum doesn't conserve → fail-fast ─────────
class SliceIneffective(unittest.TestCase):
    def test_non_conserving_total_fail_fast(self):
        # Phantom slicing: parent huge, but every narrowed window still reports
        # the SAME huge total (date not honored). Leaves stay >wall and sum
        # explodes far past parent → SLICE_INEFFECTIVE.
        def total_fn(df, dt):
            # parent (full 10y) reports 8000; any sub-window ALSO reports 8000
            return 8000
        epo = FakeEPO(total_fn=total_fn)
        spec = SD.normalize_query(keyword="radar",
                                  date_from="20150101", date_to="20241231")
        out = _run(SD.epo_slice_plan(spec, epo_client=epo))
        self.assertFalse(out["success"])
        self.assertEqual(out["error_code"], "SLICE_INEFFECTIVE")
        self.assertFalse(out["sum_check"]["ok"])


# ── depth cap: a dense window can't split under wall → truncated ─────
class DepthCapTruncated(unittest.TestCase):
    def test_depth_cap_marks_truncated(self):
        # CONSTANT density (bisection conserves exactly → sum_check passes) but
        # density so high that even a single-day window stays >wall. The planner
        # bisects to the single-day floor, still can't get under the wall, and
        # honestly marks those leaves truncated=True.
        epo = FakeEPO(density=3000.0)  # 1 day * 3000 = 3000 > wall
        spec = SD.normalize_query(keyword="radar",
                                  date_from="20200101", date_to="20200110")
        out = _run(SD.epo_slice_plan(spec, epo_client=epo))
        # structurally succeeds (conservation holds) but flags truncated leaves
        self.assertTrue(out["success"], out.get("message"))
        self.assertTrue(out["sum_check"]["ok"])
        self.assertTrue(any(s.get("truncated") for s in out["slices"]),
                        "expected at least one truncated leaf")

    def test_depth_cap_bounded(self):
        # recursion never exceeds the depth cap: with a span that can bisect ~5
        # times before hitting single-day floor, slice count stays bounded.
        epo = FakeEPO(total_fn=lambda df, dt: 60000)  # always over wall
        spec = SD.normalize_query(keyword="radar",
                                  date_from="20200101", date_to="20241231")
        out = _run(SD.epo_slice_plan(spec, epo_client=epo))
        # depth cap 6 → at most 2^6 = 64 leaves, and probe cap 32 bounds calls
        self.assertLessEqual(out["probe_calls"], SD._EPO_SLICE_PROBE_CAP)


# ── probe cap: total probe calls never exceed the budget ────────────
class ProbeCap(unittest.TestCase):
    def test_probe_calls_never_exceed_cap(self):
        epo = FakeEPO(total_fn=lambda df, dt: 60000)  # forces max splitting
        spec = SD.normalize_query(keyword="radar",
                                  date_from="20000101", date_to="20241231")
        out = _run(SD.epo_slice_plan(spec, epo_client=epo))
        self.assertLessEqual(epo.search_calls, SD._EPO_SLICE_PROBE_CAP)
        self.assertLessEqual(out["probe_calls"], SD._EPO_SLICE_PROBE_CAP)


# ── gpss + slice_plan → INVALID_PARAMS at the MCP layer ─────────────
class GpssSlicePlanRejected(unittest.TestCase):
    def test_gpss_slice_plan_invalid_params(self):
        epo = FakeEPO(total_fn=lambda df, dt: 100)
        orig = _with_clients(epo)
        try:
            out = _run(P.patent_bulk(source="gpss", keyword="radar",
                                     slice_plan=True))
        finally:
            _restore(orig)
        self.assertFalse(out["success"])
        self.assertEqual(out["error_code"], "INVALID_PARAMS")
        # zero backend calls (rejected before dispatch)
        self.assertEqual(epo.search_calls, 0)

    def test_epo_slice_plan_via_mcp_zero_records(self):
        # MCP-level slice_plan=True on epo returns the plan, ZERO records/absorb
        epo = FakeEPO(density=5.0)
        orig = _with_clients(epo)
        try:
            out = _run(P.patent_bulk(source="epo", keyword="radar",
                                     date_from="20200101", date_to="20200410",
                                     slice_plan=True))
        finally:
            _restore(orig)
        self.assertTrue(out["success"])
        self.assertIn("slices", out)
        self.assertNotIn("records", out)
        self.assertNotIn("patentdb_absorb", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
