"""Unit tests for the unified SoftScrapePolicy (plan gpss-session-reuse-batch extend).

Covers:
  - serialization (Concurrency=1 via the single asyncio.Lock)
  - delay() paces within [min,max]
  - park_cooldown / cooldown_remaining / note_block
  - guard() waits out an active cooldown before yielding
  - guard() does NOT drop requests (every entry runs its body)
  - GPSS convergence: _GPSS_POLICY exists + alias lock wired
  - ppubs: PpubsClient owns a policy

Run: .venv/bin/python tests/test_soft_scrape_policy.py
"""
import asyncio
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from patent_mcp_server.util.soft_scrape import SoftScrapePolicy


class DelayRangeTest(unittest.TestCase):
    def test_delay_sleeps_within_range(self):
        slept = []

        async def _fake_sleep(d):
            slept.append(d)

        p = SoftScrapePolicy("t", min_delay=0.4, max_delay=0.9)
        orig = asyncio.sleep
        asyncio.sleep = _fake_sleep  # type: ignore
        try:
            asyncio.run(p.delay())
        finally:
            asyncio.sleep = orig  # type: ignore
        self.assertEqual(len(slept), 1)
        self.assertGreaterEqual(slept[0], 0.4)
        self.assertLessEqual(slept[0], 0.9)

    def test_swapped_bounds_are_normalized(self):
        p = SoftScrapePolicy("t", min_delay=3.0, max_delay=1.0)
        self.assertEqual(p.min_delay, 1.0)
        self.assertEqual(p.max_delay, 3.0)


class CooldownTest(unittest.TestCase):
    def test_park_sets_remaining(self):
        p = SoftScrapePolicy("t", cooldown_default_s=50.0)
        self.assertEqual(p.cooldown_remaining, 0.0)
        p.park_cooldown()
        self.assertGreater(p.cooldown_remaining, 48.0)
        self.assertLessEqual(p.cooldown_remaining, 50.0)

    def test_park_explicit_seconds(self):
        p = SoftScrapePolicy("t")
        p.park_cooldown(5.0)
        self.assertGreater(p.cooldown_remaining, 3.5)
        self.assertLessEqual(p.cooldown_remaining, 5.0)

    def test_note_block_parks_default(self):
        p = SoftScrapePolicy("t", cooldown_default_s=20.0)
        p.note_block("429")
        self.assertGreater(p.cooldown_remaining, 18.0)


class GuardTest(unittest.TestCase):
    def test_guard_waits_out_cooldown_then_paces(self):
        slept = []

        async def _fake_sleep(d):
            slept.append(d)

        p = SoftScrapePolicy("t", min_delay=0.1, max_delay=0.1, cooldown_default_s=7.0)
        p.park_cooldown(7.0)

        async def _run():
            async with p.guard():
                return "body-ran"

        orig = asyncio.sleep
        asyncio.sleep = _fake_sleep  # type: ignore
        try:
            out = asyncio.run(_run())
        finally:
            asyncio.sleep = orig  # type: ignore
        self.assertEqual(out, "body-ran")
        # at least two sleeps: the cooldown wait + the pace
        self.assertGreaterEqual(len(slept), 2)
        self.assertTrue(any(s > 5.0 for s in slept))   # cooldown wait
        self.assertTrue(any(abs(s - 0.1) < 1e-6 for s in slept))  # pace

    def test_guard_serializes_and_runs_every_body(self):
        # Concurrency=1: bodies never overlap, and NONE are dropped.
        active = {"n": 0, "max": 0, "ran": 0}

        async def _fake_sleep(d):
            return None

        p = SoftScrapePolicy("t", min_delay=0.0, max_delay=0.0)

        async def _one():
            async with p.guard():
                active["n"] += 1
                active["max"] = max(active["max"], active["n"])
                await asyncio.sleep(0)  # yield to let others try to interleave
                active["ran"] += 1
                active["n"] -= 1

        async def _run():
            await asyncio.gather(*[_one() for _ in range(10)])

        orig = asyncio.sleep

        async def _passthrough(d):
            # only fake the policy.delay() (d==0); real yields use the original
            if d == 0:
                return await orig(0)
            return None

        asyncio.sleep = _passthrough  # type: ignore
        try:
            asyncio.run(_run())
        finally:
            asyncio.sleep = orig  # type: ignore
        self.assertEqual(active["ran"], 10)   # nothing dropped
        self.assertEqual(active["max"], 1)    # never two bodies at once


class GpssConvergenceTest(unittest.TestCase):
    def test_gpss_policy_and_alias(self):
        import patent_mcp_server.patents as P
        self.assertTrue(hasattr(P, "_GPSS_POLICY"))
        self.assertIsInstance(P._GPSS_POLICY, SoftScrapePolicy)
        # back-compat alias must BE the policy's lock
        self.assertIs(P._GPSS_SCRAPE_LOCK, P._GPSS_POLICY.lock)


class PpubsPolicyTest(unittest.TestCase):
    def test_ppubs_client_owns_policy(self):
        from patent_mcp_server.uspto.ppubs_uspto_gov import PpubsClient
        c = PpubsClient()
        self.assertIsInstance(c.policy, SoftScrapePolicy)
        self.assertEqual(c.policy.name, "USPTO-ppubs")


if __name__ == "__main__":
    unittest.main(verbosity=2)
