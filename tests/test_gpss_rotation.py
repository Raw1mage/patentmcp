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
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from patent_mcp_server.gpss.client import (  # noqa: E402
    GPSSClient,
    GPSSCondition,
    _is_quota_exhausted,
    _load_user_codes,
)


def _run(coro):
    return asyncio.run(coro)


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
        client = GPSSClient(user_codes=["A1", "A2"])
        self.assertEqual(client.user_codes, ["A1", "A2"])
        self.assertTrue(client.configured())
        self.assertEqual(client.user_code, "A1")

    def test_legacy_positional_single_code(self):
        client = GPSSClient("SINGLE")
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
        client = GPSSClient(user_codes=["A1", "A2"])
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
        client = GPSSClient(user_codes=["A1", "A2"])
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
        client = GPSSClient(user_codes=["A1", "A2"])
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
        client = GPSSClient(user_codes=["A1", "A2"])
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
        client = GPSSClient(user_codes=[])
        self.assertFalse(client.configured())
        res = _run(client.search(self._cond()))
        self.assertFalse(res["success"])
        self.assertIn("not set", res["error"])


if __name__ == "__main__":
    unittest.main()
