"""Unit tests for gpss-session-reuse-batch.

Covers:
  1 — _GpssScrapeSession holds ONE persistent httpx client (cookie reuse)
  2 — batch shares ONE session across all TW items (single client created)
  3 — batch non-TW branch routes to extract_representative_figure (PDF
      pipeline), NOT get_patent()/thumbnail (the fixed bug + thumbnail ban)
  4 — one failing item does not abort the batch (session survives)
  5 — single-call tool wrappers still pass session_client=None (throwaway)

Run: .venv/bin/python tests/test_gpss_session_batch.py
"""
import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import patent_mcp_server.patents as P


class SessionHoldsOneClientTest(unittest.TestCase):
    def test_session_creates_single_client(self):
        s = P._GpssScrapeSession()
        c1 = s._client
        c2 = s._client
        self.assertIs(c1, c2)  # same persistent client object
        asyncio.run(s.close())

    def test_session_methods_inject_same_client(self):
        # fetch_* must hand the session's own client to the impl as session_client.
        seen = {}

        async def _fake_fig_impl(pn, session_client=None):
            seen["client"] = session_client
            return {"success": True, "download_url": "x"}

        s = P._GpssScrapeSession()
        orig = P._gpss_download_representative_figure_impl
        P._gpss_download_representative_figure_impl = _fake_fig_impl  # type: ignore
        try:
            asyncio.run(s.fetch_representative_figure("TW123"))
        finally:
            P._gpss_download_representative_figure_impl = orig  # type: ignore
            asyncio.run(s.close())
        self.assertIs(seen["client"], s._client)


class BatchSharesOneSessionTest(unittest.TestCase):
    def test_batch_creates_exactly_one_session(self):
        created = {"count": 0}
        real_init = P._GpssScrapeSession.__init__

        def _counting_init(self):
            created["count"] += 1
            real_init(self)

        # TW items go through session.fetch_representative_figure; stub the impl
        # so no real network call happens.
        async def _fake_fig_impl(pn, session_client=None):
            return {"success": True, "download_url": f"fig/{pn}"}

        orig_init = P._GpssScrapeSession.__init__
        orig_impl = P._gpss_download_representative_figure_impl
        orig_pace = P._gpss_scrape_pace
        P._GpssScrapeSession.__init__ = _counting_init  # type: ignore
        P._gpss_download_representative_figure_impl = _fake_fig_impl  # type: ignore

        async def _no_pace():
            return None

        P._gpss_scrape_pace = _no_pace  # type: ignore
        try:
            out = asyncio.run(P.patentmcp_batch_download_figures(
                ["TW111", "TW222", "TW333"]))
        finally:
            P._GpssScrapeSession.__init__ = orig_init  # type: ignore
            P._gpss_download_representative_figure_impl = orig_impl  # type: ignore
            P._gpss_scrape_pace = orig_pace  # type: ignore

        self.assertEqual(created["count"], 1)  # ONE session for the whole batch
        self.assertTrue(out["success"])
        self.assertEqual(set(out["downloaded"].keys()), {"TW111", "TW222", "TW333"})


class BatchNonTwUsesPdfPipelineTest(unittest.TestCase):
    def test_non_tw_calls_extract_representative_figure_not_thumbnail(self):
        calls = {"extract": [], "get_patent": 0}

        async def _fake_extract(pn, *a, **k):
            calls["extract"].append(pn)
            return {"success": True, "download_url": f"pdf/{pn}", "page_number": 2}

        async def _fake_get_patent(pn, *a, **k):
            calls["get_patent"] += 1
            return {"success": True}  # deliberately no representative_figure_url

        orig_extract = P.extract_representative_figure
        orig_gp = P.gpatents_client.get_patent
        P.extract_representative_figure = _fake_extract  # type: ignore
        P.gpatents_client.get_patent = _fake_get_patent  # type: ignore
        try:
            out = asyncio.run(P.patentmcp_batch_download_figures(["US999", "CN888"]))
        finally:
            P.extract_representative_figure = orig_extract  # type: ignore
            P.gpatents_client.get_patent = orig_gp  # type: ignore

        # non-TW must go through the report-grade PDF pipeline...
        self.assertEqual(set(calls["extract"]), {"US999", "CN888"})
        # ...and NEVER through the old get_patent/thumbnail path (the bug).
        self.assertEqual(calls["get_patent"], 0)
        self.assertEqual(set(out["downloaded"].keys()), {"US999", "CN888"})


class BatchFailureIsolationTest(unittest.TestCase):
    def test_one_failure_does_not_abort_batch(self):
        async def _fake_extract(pn, *a, **k):
            if pn == "US_BAD":
                return {"success": False, "error": "NO_FIGURE_PAGE"}
            return {"success": True, "download_url": f"pdf/{pn}"}

        orig_extract = P.extract_representative_figure
        P.extract_representative_figure = _fake_extract  # type: ignore
        try:
            out = asyncio.run(P.patentmcp_batch_download_figures(
                ["US_OK1", "US_BAD", "US_OK2"]))
        finally:
            P.extract_representative_figure = orig_extract  # type: ignore

        self.assertTrue(out["success"])
        self.assertEqual(set(out["downloaded"].keys()), {"US_OK1", "US_OK2"})
        self.assertIn("US_BAD", out["skipped"])
        self.assertEqual(out["skipped"]["US_BAD"]["reason"], "failed")


class SingleCallStillThrowawayTest(unittest.TestCase):
    def test_single_figure_tool_uses_throwaway_client(self):
        # The single-call wrapper must NOT pass a persistent session_client;
        # the impl should see session_client=None and build a throwaway client.
        seen = {}

        async def _fake_fig_impl(pn, session_client=None):
            seen["client"] = session_client
            return {"success": True, "download_url": "x"}

        async def _no_pace():
            return None

        orig_impl = P._gpss_download_representative_figure_impl
        orig_pace = P._gpss_scrape_pace
        P._gpss_download_representative_figure_impl = _fake_fig_impl  # type: ignore
        P._gpss_scrape_pace = _no_pace  # type: ignore
        try:
            asyncio.run(P.gpss_download_representative_figure("TW123"))
        finally:
            P._gpss_download_representative_figure_impl = orig_impl  # type: ignore
            P._gpss_scrape_pace = orig_pace  # type: ignore
        self.assertIsNone(seen["client"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
