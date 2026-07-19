"""BR_20260719 §4/§4A adv-route unit tests (no live login).

Covers the two mechanisms that must hold WITHOUT hitting GPSS4:
1. §4A login gate — process-wide mutual exclusion, fail-fast on a concurrent
   login attempt (never queue, never a second session), release always frees.
2. §4 DD-4 per-session DB scope — country->dbs mapping, set-ONCE-per-session
   reuse (a second query in the same session must NOT re-POST the settings page),
   fail-fast on an unknown country.

Run: uv run pytest tests/test_br20260719_adv_route.py -q
"""
import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from patent_mcp_server.gpss4.login_gate import (  # noqa: E402
    login_gate,
    gate_status,
    GPSS4LoginBusyError,
    _GATE,
)
from patent_mcp_server.gpss4 import adv_search  # noqa: E402
from patent_mcp_server.gpss4.adv_search import (  # noqa: E402
    country_to_dbs,
    _ensure_query_ready,
    GPSS4DbScopeError,
)


def _run(coro):
    return asyncio.run(coro)


class LoginGateTest(unittest.TestCase):
    def setUp(self):
        # ensure a clean gate between tests (module-level singleton)
        _GATE._holder = None
        _GATE._acquired_at = None
        _GATE._holder_exe = None

    def test_idle_then_acquire_release(self):
        self.assertFalse(gate_status()["busy"])

        async def run():
            async with login_gate("worker_a"):
                self.assertTrue(gate_status()["busy"])
                self.assertEqual(gate_status()["holder"], "worker_a")
            # released on exit
            self.assertFalse(gate_status()["busy"])
        _run(run())

    def test_concurrent_acquire_fails_fast(self):
        """A second holder while the gate is held must raise, not queue."""
        async def run():
            async with login_gate("worker_a"):
                with self.assertRaises(GPSS4LoginBusyError) as ctx:
                    async with login_gate("worker_b"):
                        pass  # must never enter
                # error names the current holder + the refused worker
                msg = str(ctx.exception)
                self.assertIn("worker_a", msg)
                self.assertIn("worker_b", msg)
        _run(run())

    def test_release_on_exception(self):
        """Gate frees even when the body raises (finally path)."""
        async def run():
            with self.assertRaises(ValueError):
                async with login_gate("worker_a"):
                    raise ValueError("boom")
            self.assertFalse(gate_status()["busy"])
            # re-acquirable after the exception
            async with login_gate("worker_c"):
                self.assertEqual(gate_status()["holder"], "worker_c")
        _run(run())

    def test_serial_reacquire(self):
        """After a clean release the gate can be taken again (serial batch)."""
        async def run():
            for name in ("q1", "q2", "q3"):
                async with login_gate(name):
                    self.assertEqual(gate_status()["holder"], name)
                self.assertFalse(gate_status()["busy"])
        _run(run())


class CountryScopeMapTest(unittest.TestCase):
    def test_known_countries(self):
        self.assertEqual(country_to_dbs("TW"), ["TWA", "TWB"])
        self.assertEqual(country_to_dbs("cn"), ["CNA", "CNB"])  # case-insensitive
        self.assertEqual(country_to_dbs("US"), ["USA", "USB"])

    def test_unknown_country_fails_fast(self):
        with self.assertRaises(GPSS4DbScopeError):
            country_to_dbs("ZZ")
        with self.assertRaises(GPSS4DbScopeError):
            country_to_dbs("")


class _FakeSession:
    """Minimal stand-in for GPSS4Session for scope-reuse tests."""
    def __init__(self):
        self._scope_set = set()
        self.set_db_calls = []


class EnsureQueryReadyScopeTest(unittest.TestCase):
    """DD-4: scope is set ONCE per session, reused thereafter."""

    def setUp(self):
        self._orig = adv_search.set_search_databases

        async def _fake_set(s, dbs, persist=True, dump_dir=None):
            s.set_db_calls.append(list(dbs))
            # emulate the real routine recording nothing itself; _ensure_query_ready
            # is what updates s._scope_set.
            return {"ok": True, "dbs": list(dbs)}

        adv_search.set_search_databases = _fake_set

    def tearDown(self):
        adv_search.set_search_databases = self._orig

    def test_first_call_sets_scope(self):
        async def run():
            s = _FakeSession()
            got = await _ensure_query_ready(s, "TW")
            self.assertEqual(got, ["TWA", "TWB"])
            self.assertEqual(s.set_db_calls, [["TWA", "TWB"]])
            self.assertEqual(s._scope_set, {"TWA", "TWB"})
        _run(run())

    def test_second_same_country_reuses_no_repost(self):
        """A 2nd query in the same session must NOT re-POST the settings page."""
        async def run():
            s = _FakeSession()
            await _ensure_query_ready(s, "TW")
            await _ensure_query_ready(s, "TW")  # reuse
            # set_search_databases called exactly ONCE (per-session scope)
            self.assertEqual(len(s.set_db_calls), 1)
        _run(run())

    def test_different_country_extends_scope(self):
        async def run():
            s = _FakeSession()
            await _ensure_query_ready(s, "TW")
            await _ensure_query_ready(s, "CN")  # new dbs -> must set again
            self.assertEqual(len(s.set_db_calls), 2)
            self.assertTrue({"TWA", "TWB", "CNA", "CNB"}.issubset(s._scope_set))
        _run(run())

    def test_unknown_country_fails_fast_no_set(self):
        async def run():
            s = _FakeSession()
            with self.assertRaises(GPSS4DbScopeError):
                await _ensure_query_ready(s, "ZZ")
            self.assertEqual(s.set_db_calls, [])  # never touched the settings page
        _run(run())


class ResolveAppnosDispatchTest(unittest.TestCase):
    """BR_20260719 缺陷A/B: gpss4_resolve_appnos 入口分流 + render_pending 降級。

    Mock resolve_one / _ensure_query_ready / shared_session so the whole batch
    loop runs WITHOUT hitting GPSS4. Asserts:
      A. 公開/公告識別號 passthrough (already_identifier, 不進 adv)
      B. hits>0-no-render 降為 render_pending, 不中斷整批、不計 consecutive error
    """

    def _run_resolve(self, nums, resolve_side_effect):
        import tempfile
        import json
        import importlib
        from patent_mcp_server.gpss4 import adv_search, session_manager

        patents = importlib.import_module("patent_mcp_server.patents")

        # ---- stub the three injected dependencies -------------------------
        calls = {"resolve_one": 0}

        async def _fake_resolve_one(s, num, axis="apply", country="TW",
                                    dump_dir=None):
            calls["resolve_one"] += 1
            return resolve_side_effect(num)

        async def _fake_ensure_query_ready(s, country):
            return ["TWA", "TWB"]

        class _FakeSharedSession:
            def __init__(self, holder):
                pass

            async def __aenter__(self):
                return object()

            async def __aexit__(self, *a):
                return None

        orig = (adv_search.resolve_one, adv_search._ensure_query_ready,
                session_manager.shared_session)
        adv_search.resolve_one = _fake_resolve_one
        adv_search._ensure_query_ready = _fake_ensure_query_ready
        session_manager.shared_session = _FakeSharedSession
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".txt",
                                             delete=False) as tf:
                tf.write("\n".join(nums) + "\n")
                appnos_file = tf.name
            with tempfile.NamedTemporaryFile("w", suffix=".jsonl",
                                             delete=False) as of:
                out_file = of.name
            res = _run(patents.gpss4_resolve_appnos(
                appnos_file=appnos_file, out_file=out_file, max_items=100))
            rows = [json.loads(ln) for ln in open(out_file, encoding="utf-8")
                    if ln.strip()]
            return res, rows, calls
        finally:
            (adv_search.resolve_one, adv_search._ensure_query_ready,
             session_manager.shared_session) = orig
            for p in (appnos_file, out_file):
                try:
                    os.unlink(p)
                except OSError:
                    pass

    def test_identifier_passthrough_not_dispatched(self):
        """缺陷A: 西元年公開號不進 resolve_one, 標 already_identifier。"""
        from patent_mcp_server.gpss4.adv_search import AdvPatent

        def side(num):
            return AdvPatent(pat_no="TW999999", apply_no=num)

        nums = ["TW200644333", "TW202242807"]  # 兩件都是公開號
        res, rows, calls = self._run_resolve(nums, side)
        self.assertEqual(calls["resolve_one"], 0, "公開號不該投 adv")
        self.assertTrue(res.get("success"))
        self.assertEqual([r["status"] for r in rows],
                         ["already_identifier", "already_identifier"])
        self.assertEqual(rows[0]["pubno"], "TW200644333")

    def test_mixed_batch_render_pending_does_not_break_batch(self):
        """缺陷B: 民國年申請號中 render_pending 不中斷整批、不計 consecutive。"""
        from patent_mcp_server.gpss4.adv_search import (
            AdvPatent, GPSS4AdvRenderPending,
        )

        def side(num):
            # 10 件民國年申請號，每一件都 render_pending (若計 consecutive 就會
            # 在第 8 件中斷)。驗證降級後整批跑完。
            raise GPSS4AdvRenderPending(
                {"全部": 2, "本國公開": 0, "本國公告": 2}, "<shell/>")

        nums = [f"TW1091{i:05d}" for i in range(10)]  # 10 件民國年申請號
        res, rows, calls = self._run_resolve(nums, side)
        self.assertEqual(calls["resolve_one"], 10, "每件都該進 adv")
        self.assertTrue(res.get("success"), "render_pending 不該中斷整批")
        self.assertNotEqual(res.get("error_code"), "CONSECUTIVE_ERRORS")
        self.assertEqual(sum(r["status"] == "render_pending" for r in rows), 10)
        self.assertEqual(res["stats"]["render_pending"], 10)
        self.assertEqual(res["stats"]["error"], 0)

    def test_hard_error_still_counts_consecutive(self):
        """回歸防護: 真硬 error 仍累計 consecutive 並在第 8 件中斷。"""
        from patent_mcp_server.gpss4.adv_search import GPSS4AdvSearchError

        def side(num):
            raise GPSS4AdvSearchError("adv form not reachable")

        nums = [f"TW1091{i:05d}" for i in range(10)]
        res, rows, calls = self._run_resolve(nums, side)
        self.assertFalse(res.get("success"))
        self.assertEqual(res.get("error_code"), "CONSECUTIVE_ERRORS")


if __name__ == "__main__":
    unittest.main()
