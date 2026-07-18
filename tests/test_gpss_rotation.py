"""Tests for GPSSClient N-account rotation (plan patentmcp_gpss-account-rotation).

Covers test-vectors.json TV-1 ~ TV-5. Drives the REAL GPSSClient.search()
rotation loop by faking the HTTP layer (self._client.get), so account-pool
parsing, quota-exhaustion detection (DD-2), rotation (DD-1/DD-3), and
all-exhausted fail-fast (DD-5) are exercised end-to-end.

Run: uv run pytest tests/test_gpss_rotation.py -q
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from patent_mcp_server.gpss.client import (  # noqa: E402
    GPSSClient,
    GPSSCondition,
    _is_quota_exhausted,
    _load_user_codes,
)
from patent_mcp_server.gpss.quota_state import QuotaStateStore, window_key  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# DD-8: exhausted state now persists in a cross-process sqlite sidecar. Give each
# test its OWN isolated on-disk sidecar so state doesn't bleed across tests (and
# never touch the real patentdb/ store). Scratch lands in XDG runtime (0700),
# never /tmp (security 天条).
_XDG = os.environ.get("XDG_RUNTIME_DIR") or os.environ.get("XDG_CACHE_HOME") \
    or os.path.join(os.path.expanduser("~"), ".cache")
_SCRATCH_ROOT = os.path.join(_XDG, "patentmcp-tests")
os.makedirs(_SCRATCH_ROOT, mode=0o700, exist_ok=True)


def _isolated_store() -> QuotaStateStore:
    d = tempfile.mkdtemp(prefix="gpssq_", dir=_SCRATCH_ROOT)
    return QuotaStateStore(db_path=Path(d) / "quota.sqlite")


def _isolated_client(**kw) -> GPSSClient:
    kw.setdefault("quota_store", _isolated_store())
    return GPSSClient(**kw)


class _FakeResp:
    """Minimal stand-in for an httpx.Response."""

    def __init__(self, payload):
        # payload is a dict already shaped like the GPSS JSON envelope.
        self.text = json.dumps(payload)

    def raise_for_status(self):
        return None


def _quota_exhausted_payload():
    return {"gpss-API": {"status": "success", "message": "Over download quantity"}}


def _no_record_payload():
    return {"gpss-API": {"status": "success", "message": "no record found"}}


def _hit_payload(total=5):
    return {"gpss-API": {"status": "success", "total-rec": total, "qty-rec": total}}


def _patch_http(client, responses_by_code):
    """Patch client._client.get so it returns a response keyed by the userCode
    present in the requested URL. records the userCodes actually hit."""
    hits = []

    async def _fake_get(url):
        # userCode=<code>& is the first query param search() builds.
        code = None
        for part in url.split("?", 1)[1].split("&"):
            if part.startswith("userCode="):
                code = part[len("userCode="):]
                break
        hits.append(code)
        payload = responses_by_code[code]
        return _FakeResp(payload)

    client._client.get = _fake_get  # type: ignore[assignment]
    return hits


# ── TV-1 / TV-2: account-pool parsing ──────────────────────────────────

class TestPoolParsing(unittest.TestCase):
    def test_tv1_comma_split_strip_dedup_order(self):
        codes = _load_user_codes(None) if False else None
        with mock.patch.dict(os.environ, {
            "GPSS_USER_CODES": " c2d198B6924a37D6 , f77fB093dfdb34FD ,c2d198B6924a37D6, ",
        }, clear=False):
            os.environ.pop("GPSS_USER_CODE", None)
            codes = _load_user_codes(None)
        self.assertEqual(codes, ["c2d198B6924a37D6", "f77fB093dfdb34FD"])

    def test_tv2_falls_back_to_legacy_single_code(self):
        with mock.patch.dict(os.environ, {
            "GPSS_USER_CODES": "",
            "GPSS_USER_CODE": "f77fB093dfdb34FD",
        }, clear=False):
            codes = _load_user_codes(None)
        self.assertEqual(codes, ["f77fB093dfdb34FD"])

    def test_explicit_arg_overrides_env(self):
        client = _isolated_client(user_codes=["A1", "A2"])
        self.assertEqual(client.user_codes, ["A1", "A2"])
        self.assertTrue(client.configured())
        self.assertEqual(client.user_code, "A1")

    def test_legacy_positional_single_code(self):
        client = _isolated_client(user_code="SINGLE")
        self.assertEqual(client.user_codes, ["SINGLE"])
        self.assertEqual(client.user_code, "SINGLE")


# ── quota-exhaustion signal detection (DD-2) ──────────────────────────

class TestQuotaSignal(unittest.TestCase):
    def test_over_download_quantity_is_exhaustion(self):
        self.assertTrue(_is_quota_exhausted("Over download quantity"))
        self.assertTrue(_is_quota_exhausted("xxx over download quantity yyy"))

    def test_over_search_quantity_is_exhaustion(self):
        self.assertTrue(_is_quota_exhausted("Over search quantity"))

    def test_no_record_is_not_exhaustion(self):
        self.assertFalse(_is_quota_exhausted("no record found"))

    def test_empty_is_not_exhaustion(self):
        self.assertFalse(_is_quota_exhausted(None))
        self.assertFalse(_is_quota_exhausted(""))


# ── TV-3: first exhausted → rotate to second, succeed ─────────────────

class TestRotation(unittest.TestCase):
    def _cond(self):
        return [GPSSCondition("TI", "radar")]

    def test_tv3_first_exhausted_rotates_to_second(self):
        client = _isolated_client(user_codes=["A1", "A2"])
        hits = _patch_http(client, {
            "A1": _quota_exhausted_payload(),
            "A2": _hit_payload(total=5),
        })
        res = _run(client.search(self._cond()))
        self.assertTrue(res["success"])
        self.assertEqual(res["total"], 5)
        self.assertEqual(hits, ["A1", "A2"])  # tried A1, rotated to A2
        self.assertEqual(client.user_code, "A2")  # cursor moved

    def test_tv4_all_exhausted_fail_fast(self):
        client = _isolated_client(user_codes=["A1", "A2"])
        hits = _patch_http(client, {
            "A1": _quota_exhausted_payload(),
            "A2": _quota_exhausted_payload(),
        })
        res = _run(client.search(self._cond()))
        self.assertFalse(res["success"])
        self.assertEqual(res["error_code"], "GPSS_ALL_ACCOUNTS_EXHAUSTED")
        self.assertEqual(res["accounts_tried"], 2)
        self.assertEqual(hits, ["A1", "A2"])

    def test_tv5_no_record_does_not_rotate(self):
        client = _isolated_client(user_codes=["A1", "A2"])
        hits = _patch_http(client, {
            "A1": _no_record_payload(),
            "A2": _hit_payload(total=99),  # must NOT be reached
        })
        res = _run(client.search(self._cond()))
        # no-record is a normal (unsuccessful) result, NOT rotation.
        self.assertFalse(res["success"])
        self.assertEqual(res["message"], "no record found")
        self.assertEqual(hits, ["A1"])  # only A1 hit, no rotation
        self.assertEqual(client.user_code, "A1")  # cursor unchanged

    def test_exhausted_account_skipped_on_next_search(self):
        client = _isolated_client(user_codes=["A1", "A2"])
        _patch_http(client, {
            "A1": _quota_exhausted_payload(),
            "A2": _hit_payload(total=3),
        })
        _run(client.search(self._cond()))  # A1 exhausted, now on A2
        # second search should go straight to A2 (A1 stays exhausted, DD-3)
        hits2 = _patch_http(client, {
            "A1": _quota_exhausted_payload(),
            "A2": _hit_payload(total=3),
        })
        res = _run(client.search(self._cond()))
        self.assertTrue(res["success"])
        self.assertEqual(hits2, ["A2"])  # A1 skipped

    def test_empty_pool_returns_not_set(self):
        client = _isolated_client(user_codes=[])
        self.assertFalse(client.configured())
        res = _run(client.search(self._cond()))
        self.assertFalse(res["success"])
        self.assertIn("not set", res["error"])


# ── BR_20260718: window_key quantisation (DD-7) ─────────────────────────
from datetime import datetime, timezone, timedelta  # noqa: E402

_TPE = timezone(timedelta(hours=8))


class TestWindowKey(unittest.TestCase):
    """DD-7: window_key must be STABLE within a GPSS quota window and DISTINCT
    across windows, so an exhausted account revives implicitly on boundary."""

    def test_weekday_daytime_is_narrow_window(self):
        # Fri 2026-07-17 10:00 TPE -> weekday daytime narrow window.
        k = window_key(datetime(2026, 7, 17, 10, 0, tzinfo=_TPE))
        self.assertEqual(k, "2026-07-17:narrow")

    def test_narrow_window_is_stable_within_08_18(self):
        k1 = window_key(datetime(2026, 7, 17, 8, 1, tzinfo=_TPE))
        k2 = window_key(datetime(2026, 7, 17, 17, 59, tzinfo=_TPE))
        self.assertEqual(k1, k2)

    def test_crossing_18_00_changes_key(self):
        # 17:59 narrow vs 18:01 wide -> DIFFERENT keys (revival boundary).
        narrow = window_key(datetime(2026, 7, 17, 17, 59, tzinfo=_TPE))
        wide = window_key(datetime(2026, 7, 17, 18, 1, tzinfo=_TPE))
        self.assertNotEqual(narrow, wide)

    def test_overnight_wide_window_does_not_fracture_at_midnight(self):
        # Thu 18:30 and the following Fri 02:00 belong to ONE overnight wide
        # window anchored on Thursday.
        thu_eve = window_key(datetime(2026, 7, 16, 18, 30, tzinfo=_TPE))
        fri_predawn = window_key(datetime(2026, 7, 17, 2, 0, tzinfo=_TPE))
        self.assertEqual(thu_eve, fri_predawn)
        self.assertEqual(thu_eve, "2026-07-16:wide")

    def test_weekend_is_one_wide_window_anchored_friday(self):
        # Sat and Sun of the same weekend share one key anchored on Friday.
        sat = window_key(datetime(2026, 7, 18, 12, 0, tzinfo=_TPE))
        sun = window_key(datetime(2026, 7, 19, 23, 0, tzinfo=_TPE))
        self.assertEqual(sat, sun)
        self.assertEqual(sat, "2026-07-17:wide")


class TestWindowRevival(unittest.TestCase):
    """DD-7: an account exhausted in one window is skipped THAT window but
    revives once the window_key rolls over — no restart, no explicit clear."""

    def _cond(self):
        return [GPSSCondition("TI", "radar")]

    def test_exhausted_account_revives_next_window(self):
        store = _isolated_store()
        w1 = "2026-07-17:narrow"
        w2 = "2026-07-17:wide"

        # In window w1, mark A1 exhausted directly.
        store.mark_exhausted("A1", key=w1)
        self.assertTrue(store.is_exhausted("A1", key=w1))
        # Same account is NOT exhausted under the next window's key.
        self.assertFalse(store.is_exhausted("A1", key=w2))

    def test_client_skips_in_window_then_retries_next_window(self):
        # window-frozen store: force is_exhausted to consult a mutable window.
        store = _isolated_store()
        cur = {"key": "2026-07-17:narrow"}
        orig_mark = store.mark_exhausted
        orig_is = store.is_exhausted
        store.mark_exhausted = lambda acct, key=None: orig_mark(acct, key=cur["key"])  # type: ignore
        store.is_exhausted = lambda acct, key=None: orig_is(acct, key=cur["key"])  # type: ignore

        client = GPSSClient(user_codes=["A1", "A2"], quota_store=store)
        # Window 1: A1 exhausted -> rotate to A2.
        _patch_http(client, {"A1": _quota_exhausted_payload(), "A2": _hit_payload(3)})
        _run(client.search(self._cond()))
        self.assertTrue(store.is_exhausted("A1"))

        # Roll the window over: A1 must be tried again from cursor 0.
        cur["key"] = "2026-07-17:wide"
        client._cursor = 0
        hits2 = _patch_http(client, {"A1": _hit_payload(7), "A2": _hit_payload(9)})
        res = _run(client.search(self._cond()))
        self.assertTrue(res["success"])
        self.assertEqual(hits2, ["A1"])  # A1 revived, hit first


class TestCrossProcessSharing(unittest.TestCase):
    """DD-8: two GPSSClient instances (simulating parallel subagent processes)
    that share ONE sidecar see each other's exhausted marks — roots out the
    DD-97 stampede where both would independently burn from cursor #0."""

    def _cond(self):
        return [GPSSCondition("TI", "radar")]

    def test_second_process_skips_account_first_process_exhausted(self):
        shared = _isolated_store()
        # Process 1 exhausts A1, rotates to A2.
        c1 = GPSSClient(user_codes=["A1", "A2"], quota_store=shared)
        _patch_http(c1, {"A1": _quota_exhausted_payload(), "A2": _hit_payload(3)})
        _run(c1.search(self._cond()))

        # Process 2 starts fresh (own cursor #0) but shares the sidecar: it must
        # skip A1 straight to A2 without re-hitting the quota wall.
        c2 = GPSSClient(user_codes=["A1", "A2"], quota_store=shared)
        hits2 = _patch_http(c2, {"A1": _quota_exhausted_payload(), "A2": _hit_payload(5)})
        res = _run(c2.search(self._cond()))
        self.assertTrue(res["success"])
        self.assertEqual(hits2, ["A2"])  # A1 skipped by the shared sidecar


if __name__ == "__main__":
    unittest.main()
