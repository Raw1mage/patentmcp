"""BR_20260718 regression tests — two fixes:

1. gpss/client.py: unparseable (truncated) JSON body is retried on a fresh
   one-shot connection; if still unparseable, returns a typed
   GPSS_TRUNCATED_BODY error with transport semantics (never read as zero
   hits).
2. gpss4/adv_search.py: the search-form watcher shell (chkURL contract) is
   recognised; DB_OK with 全部(0) is a genuine zero-hit -> structured empty
   pool instead of the misleading "簡詳目並列 view switch failed" error.

Run: uv run pytest tests/test_br20260718_fixes.py -q
"""
import asyncio
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from patent_mcp_server.gpss.client import (  # noqa: E402
    GPSSClient,
    GPSSCondition,
    _TRUNCATION_RETRIES,
)
from patent_mcp_server.gpss4.adv_search import (  # noqa: E402
    _CHKURL_RE,
    _WATCH_COUNT_RE,
    GPSS4AdvZeroHits,
)


def _run(coro):
    return asyncio.run(coro)


class _FakeResp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


_GOOD_BODY = json.dumps(
    {"gpss-API": {"status": "success", "total-rec": 3, "qty-rec": 3}})
# a truncated body: valid JSON prefix, cut mid-stream (all 3 sanitize layers fail)
_TRUNCATED_BODY = _GOOD_BODY[: len(_GOOD_BODY) // 2]


class TestTruncationRetry(unittest.TestCase):
    """BR_20260718 fix 1: fresh-connection retry on parse failure."""

    def _client(self):
        return GPSSClient(user_codes=["C1"])

    def _cond(self):
        return [GPSSCondition("TI", "radar")]

    def test_fresh_retry_recovers_truncated_body(self):
        client = self._client()

        async def _fake_get(url):
            return _FakeResp(_TRUNCATED_BODY)

        fresh_calls = []

        async def _fake_fresh(url):
            fresh_calls.append(url)
            return _FakeResp(_GOOD_BODY)

        client._client.get = _fake_get  # type: ignore[assignment]
        client._fresh_get = _fake_fresh  # type: ignore[assignment]
        res = _run(client.search(self._cond()))
        self.assertTrue(res["success"])
        self.assertEqual(res["total"], 3)
        self.assertEqual(len(fresh_calls), 1)

    def test_exhausted_retries_return_typed_transport_error(self):
        client = self._client()

        async def _fake_get(url):
            return _FakeResp(_TRUNCATED_BODY)

        fresh_calls = []

        async def _fake_fresh(url):
            fresh_calls.append(url)
            return _FakeResp(_TRUNCATED_BODY)

        client._client.get = _fake_get  # type: ignore[assignment]
        client._fresh_get = _fake_fresh  # type: ignore[assignment]
        res = _run(client.search(self._cond()))
        self.assertFalse(res["success"])
        self.assertEqual(res["error_code"], "GPSS_TRUNCATED_BODY")
        self.assertEqual(res["transport"], "truncation")
        self.assertIn("NOT an empty result", res["error"])
        self.assertEqual(len(fresh_calls), _TRUNCATION_RETRIES)
        # raw evidence carried for downstream triage
        self.assertTrue(res["raw"].startswith(_TRUNCATED_BODY[:50]))

    def test_clean_body_takes_no_retry(self):
        client = self._client()

        async def _fake_get(url):
            return _FakeResp(_GOOD_BODY)

        async def _fake_fresh(url):
            raise AssertionError("fresh retry must not fire on a clean body")

        client._client.get = _fake_get  # type: ignore[assignment]
        client._fresh_get = _fake_fresh  # type: ignore[assignment]
        res = _run(client.search(self._cond()))
        self.assertTrue(res["success"])


# --- fix 2: search-form watcher shell contract (live-captured 2026-07-18) ----

# minimal slice of the REAL not-ready form shell (probe p3_post1.html)
_SHELL_HTML = (
    'var NeedCheck=1,StartSearch=0,count=0,MAXcount=1000,ptmp="kmwork/00032",'
    'kmtmp=ptmp.substr(0,ptmp.indexOf("/"));var curtslot=1;'
    'var chkURL="/gpss4/gpsskmc/ttsserv_watch?"+kmtmp+"/km.swp:22:"'
    '+curtslot+":"+encodeURIComponent("全部")+":";'
)
# the REAL DB_OK watch body for a zero-hit search (probe p2_watch1.html)
_WATCH_ZERO = (
    '<table border=0>\n'
    '<tr><td><img src="/gpss4/gpsskm/images/result_icon.png">'
    '<font color=gray>全部(0)</font></td></tr>\n'
    '<tr><td><img src="/gpss4/gpsskm/images/result_icon.png">'
    '<font color=gray>美國公開(0)</font></td></tr>\n'
    '<tr><td><img src="/gpss4/gpsskm/images/result_icon.png">'
    '<font color=gray>美國公告(0)</font></td></tr>\n'
    '</table><!--DB_OK->'
)
_WATCH_HITS = _WATCH_ZERO.replace("全部(0)", "全部(1,234)").replace(
    "美國公開(0)", "美國公開(1,000)").replace("美國公告(0)", "美國公告(234)")


class TestSearchReadyShellContract(unittest.TestCase):
    """BR_20260718 fix 2: chkURL shell recognition + watch-count parsing."""

    def test_chkurl_regex_matches_live_shell(self):
        m = _CHKURL_RE.search(_SHELL_HTML)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "/gpss4/gpsskmc/ttsserv_watch?")
        self.assertEqual(m.group(2), "/km.swp:22:")

    def test_chkurl_regex_ignores_result_page_aurl(self):
        # the RESULT page's AURL watcher must not match the chkURL contract
        aurl = ('var AURL="/gpss4/gpsskmc/ttsserv_watch?"+kmtmp'
                '+"/km.swp:22:1:"+encodeURIComponent("全部")+":";')
        self.assertIsNone(_CHKURL_RE.search(aurl))

    def test_watch_counts_zero(self):
        counts = {n.strip(): int(v.replace(",", ""))
                  for n, v in _WATCH_COUNT_RE.findall(_WATCH_ZERO)}
        self.assertEqual(counts, {"全部": 0, "美國公開": 0, "美國公告": 0})

    def test_watch_counts_hits_with_thousands_separator(self):
        counts = {n.strip(): int(v.replace(",", ""))
                  for n, v in _WATCH_COUNT_RE.findall(_WATCH_HITS)}
        self.assertEqual(counts["全部"], 1234)
        self.assertEqual(counts["美國公開"], 1000)

    def test_zero_hits_exception_carries_counts(self):
        z = GPSS4AdvZeroHits({"全部": 0, "美國公開": 0})
        self.assertEqual(z.counts["全部"], 0)
        self.assertIn("zero hits", str(z))


if __name__ == "__main__":
    unittest.main()
