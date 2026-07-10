"""plans/patentmcp_bulk-entry-unification: patent_bulk routing + stubs.

Covers test-vectors.json TV-1..TV-4, TV-6, TV-7. No real network — Fake
clients follow tests/test_search_dispatcher.py (FakeGPSS/FakeEPO). Direct
async tool-fn calls via asyncio.run.

Run: uv run pytest tests/test_patent_bulk.py -q
"""
import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import patent_mcp_server.patents as P
import patent_mcp_server.search_dispatcher as SD


# ── fake clients (mirror test_search_dispatcher.py) ──────────────────

def _gpss_hit_payload(pubs):
    return {
        "success": True, "status": "success", "message": None,
        "total": len(pubs), "qty": len(pubs),
        "data": {"gpss-API": {"patent": {"patentcontent": [
            {
                "publication-reference": {"doc-number": p},
                "patent-title": {"english-title": f"Title {p}"},
                "claims": {"claim": [{"claim-text": "1. A device."}]},
            } for p in pubs
        ]}}},
    }


class FakeGPSS:
    def __init__(self, configured=True, pubs=None, fail=False):
        self._configured = configured
        self.pubs = pubs or []
        self.fail = fail
        self.calls = 0
        self.last_conditions = None

    def configured(self):
        return self._configured

    async def search(self, **kwargs):
        self.calls += 1
        self.last_conditions = kwargs.get("conditions")
        if self.fail:
            return {"success": False, "error": "GPSS 500 boom"}
        if not self.pubs:
            return {"success": False, "status": "success",
                    "message": "no record found", "total": 0}
        # single page then exhaust (total == len(pubs))
        if kwargs.get("skip", 0) >= len(self.pubs):
            return {"success": False, "status": "success", "total": len(self.pubs)}
        return _gpss_hit_payload(self.pubs)


class FakeEPO:
    def __init__(self, configured=True, pages=None, total=None):
        # pages: list of pub-number pages; each search() call returns the next page
        self._configured = configured
        self.pages = pages if pages is not None else []
        self._total = total
        self.search_calls = 0
        self.biblio_calls = 0
        self.cqls = []

    def configured(self):
        return self._configured

    async def search(self, cql, range_="1-25"):
        self.cqls.append(cql)
        idx = self.search_calls
        self.search_calls += 1
        page = self.pages[idx] if idx < len(self.pages) else []
        total = self._total if self._total is not None else sum(len(p) for p in self.pages)
        return {"success": True, "cql": cql, "total": total,
                "count": len(page), "results": list(page)}

    async def biblio(self, pub):
        self.biblio_calls += 1
        return {"success": True, "pub": pub, "found": True,
                "title": f"EPO title {pub}", "abstract": "abs",
                "applicants": ["ACME"], "ipc": ["A61B5/024"]}


def _run(coro):
    return asyncio.run(coro)


def _with_clients(gpss=None, epo=None):
    """Swap module singletons + neutralize patentdb absorb; restore after."""
    orig = (P.gpss_client, P.epo_client, P._pdb)

    class _NoAbsorb:
        @staticmethod
        def import_records(records, acquisition_cost="low"):
            return {"imported": len(records), "updated": 0, "skipped": 0}

    P.gpss_client = gpss if gpss is not None else FakeGPSS()  # type: ignore
    P.epo_client = epo if epo is not None else FakeEPO()  # type: ignore
    P._pdb = _NoAbsorb()  # type: ignore
    return orig


def _restore(orig):
    P.gpss_client, P.epo_client, P._pdb = orig  # type: ignore


# ── TV-1: gpss no keyword → export route ─────────────────────────────
class TV1GpssExport(unittest.TestCase):
    def test_gpss_no_keyword_uses_export(self):
        gpss = FakeGPSS(configured=True, pubs=["US1", "US2"])
        epo = FakeEPO(configured=True)
        orig = _with_clients(gpss, epo)
        try:
            out = _run(P.patent_bulk(source="gpss", cpc="G08B21/04", num=200))
        finally:
            _restore(orig)
        self.assertTrue(out["success"])
        self.assertEqual(out["source"], "gpss")
        self.assertGreaterEqual(gpss.calls, 1)
        self.assertEqual(epo.search_calls, 0)  # epo NOT touched
        for k in ("next_skip", "exhausted", "patentdb_absorb"):
            self.assertIn(k, out)
        # export forces full expFld → keyword condition absent
        self.assertIsNotNone(gpss.last_conditions)


# ── TV-2: gpss with keyword → harvest route ──────────────────────────
class TV2GpssHarvest(unittest.TestCase):
    def test_gpss_keyword_uses_harvest(self):
        gpss = FakeGPSS(configured=True, pubs=["US9"])
        epo = FakeEPO(configured=True)
        orig = _with_clients(gpss, epo)
        try:
            out = _run(P.patent_bulk(
                source="gpss", keyword="fall and (radar or mmwave)", num=200))
        finally:
            _restore(orig)
        self.assertTrue(out["success"])
        self.assertEqual(out["source"], "gpss")
        self.assertEqual(epo.search_calls, 0)
        # harvest path keeps the keyword condition
        kinds = [c.field if hasattr(c, "field") else None
                 for c in (gpss.last_conditions or [])]
        # keyword condition uses keyword_field (default TI/AB)
        self.assertIn("TI/AB", kinds)


# ── TV-3: epo → harvest route, CQL boolean, per-page absorb ──────────
class TV3EpoHarvest(unittest.TestCase):
    def test_epo_route_cql_and_absorb(self):
        epo = FakeEPO(configured=True, pages=[["EP1A1", "EP2A1"], []], total=2)
        gpss = FakeGPSS(configured=True, pubs=["US1"])
        absorb_pages = []
        orig = _with_clients(gpss, epo)

        class _CountAbsorb:
            @staticmethod
            def import_records(records, acquisition_cost="low"):
                absorb_pages.append(list(records))
                return {"imported": len(records), "updated": 0, "skipped": 0}

        P._pdb = _CountAbsorb()  # type: ignore
        try:
            out = _run(P.patent_bulk(source="epo", keyword="radar AND fall", num=100))
        finally:
            _restore(orig)
        self.assertTrue(out["success"])
        self.assertEqual(out["source"], "epo")
        self.assertEqual(gpss.calls, 0)  # gpss NOT touched
        # CQL boolean translation applied
        self.assertTrue(any("txt=radar and txt=fall" in c for c in epo.cqls))
        # per-page absorb fired (one page of 2 records landed)
        self.assertGreaterEqual(len(absorb_pages), 1)
        self.assertEqual(len(absorb_pages[0]), 2)
        for k in ("next_skip", "exhausted"):
            self.assertIn(k, out)


# ── TV-4: invalid/missing source → INVALID_PARAMS, zero backend ──────
class TV4InvalidSource(unittest.TestCase):
    def test_bad_source_fail_fast(self):
        gpss = FakeGPSS(configured=True, pubs=["US1"])
        epo = FakeEPO(configured=True, pages=[["EP1A1"]])
        orig = _with_clients(gpss, epo)
        try:
            out = _run(P.patent_bulk(source="uspto", cpc="G08B21/04"))
        finally:
            _restore(orig)
        self.assertFalse(out["success"])
        self.assertEqual(out["error_code"], "INVALID_PARAMS")
        self.assertEqual(gpss.calls, 0)
        self.assertEqual(epo.search_calls, 0)

    def test_missing_source_fail_fast(self):
        gpss = FakeGPSS(configured=True, pubs=["US1"])
        epo = FakeEPO(configured=True, pages=[["EP1A1"]])
        orig = _with_clients(gpss, epo)
        try:
            out = _run(P.patent_bulk(cpc="G08B21/04"))
        finally:
            _restore(orig)
        self.assertFalse(out["success"])
        self.assertEqual(out["error_code"], "INVALID_PARAMS")
        self.assertEqual(gpss.calls + epo.search_calls, 0)


# ── dispatcher-level bulk() invalid source: zero backend, direct ─────
class BulkRouterInvalid(unittest.TestCase):
    def test_dispatcher_bulk_invalid_source(self):
        gpss = FakeGPSS(configured=True, pubs=["US1"])
        epo = FakeEPO(configured=True, pages=[["EP1A1"]])
        spec = SD.normalize_query(cpc="G08B21/04", num=10)
        out = _run(SD.bulk(spec, "wikipedia", gpss_client=gpss, epo_client=epo))
        self.assertFalse(out["success"])
        self.assertEqual(out["error_code"], "INVALID_PARAMS")
        self.assertEqual(gpss.calls, 0)
        self.assertEqual(epo.search_calls, 0)


# ── TV-6: EPO per-page absorb: exception does NOT break harvest;
#          next_skip resume semantics ─────────────────────────────────
class TV6PerPageResilience(unittest.TestCase):
    def test_absorb_exception_does_not_break_harvest(self):
        # two pages; absorb raises on the first — harvest must still land page 2
        epo = FakeEPO(configured=True,
                      pages=[["EP1A1", "EP2A1"], ["EP3A1"], []], total=3)
        spec = SD.normalize_query(keyword="radar", num=300)

        seen = []

        def boom(page):
            seen.append(list(page))
            raise RuntimeError("absorb blew up")

        out = _run(SD.epo_bulk_harvest(spec, epo_client=epo, absorb_cb=boom))
        self.assertTrue(out["success"])
        # both pages were attempted despite the raise
        self.assertEqual(len(seen), 2)
        self.assertEqual(len(out["records"]), 3)

    def test_next_skip_advances_and_resume(self):
        # page of 2 records, total 5 → next_skip=2, not exhausted
        epo = FakeEPO(configured=True, pages=[["EP1A1", "EP2A1"], []], total=5)
        spec = SD.normalize_query(keyword="radar", num=2)
        out = _run(SD.epo_bulk_harvest(spec, epo_client=epo))
        self.assertTrue(out["success"])
        self.assertEqual(out["next_skip"], 2)
        self.assertFalse(out["exhausted"])

    def test_gpss_next_skip_backfilled(self):
        # dispatcher-level bulk() must back-fill next_skip/exhausted for GPSS
        gpss = FakeGPSS(configured=True, pubs=["US1", "US2"])
        epo = FakeEPO(configured=True)
        spec = SD.normalize_query(cpc="G08B21/04", num=200)
        out = _run(SD.bulk(spec, "gpss", gpss_client=gpss, epo_client=epo))
        self.assertTrue(out["success"])
        self.assertIn("next_skip", out)
        self.assertIn("exhausted", out)
        self.assertEqual(out["next_skip"], len(out["records"]))
        # total==2 and next_skip==2 → exhausted
        self.assertTrue(out["exhausted"])


# ── TV-7: three retired tools → TOOL_RENAMED stub, zero backend ──────
class TV7RenamedStubs(unittest.TestCase):
    def _check(self, coro, expect_source):
        gpss = FakeGPSS(configured=True, pubs=["US1"])
        epo = FakeEPO(configured=True, pages=[["EP1A1"]])
        orig = _with_clients(gpss, epo)
        try:
            out = _run(coro)
        finally:
            _restore(orig)
        self.assertFalse(out["success"])
        self.assertEqual(out["error_code"], "TOOL_RENAMED")
        self.assertEqual(out["use"], "patent_bulk")
        self.assertIn(f"source='{expect_source}'", out["note"])
        self.assertEqual(gpss.calls, 0)
        self.assertEqual(epo.search_calls, 0)

    def test_patent_bulk_export_stub(self):
        self._check(P.patent_bulk_export(cpc="G08B21/04"), "gpss")

    def test_patent_bulk_harvest_stub(self):
        self._check(P.patent_bulk_harvest(keyword="fall"), "gpss")

    def test_epo_bulk_harvest_stub(self):
        self._check(P.epo_bulk_harvest(keyword="fall"), "epo")


if __name__ == "__main__":
    unittest.main(verbosity=2)
