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


if __name__ == "__main__":
    unittest.main()
