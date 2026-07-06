"""BR_20260706: retired search tools must return a typed TOOL_RENAMED
redirect envelope (one release cycle), never run a search or raise
unknown-tool. Guards the deprecation-stub contract."""

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import patent_mcp_server.patents as P


class ToolRenamedStubs(unittest.TestCase):
    def _check(self, coro):
        out = asyncio.run(coro)
        self.assertFalse(out["success"])
        self.assertEqual(out["error_code"], "TOOL_RENAMED")
        self.assertEqual(out["use"], "patent_search")
        self.assertIn("patent_search", out["note"])

    def test_gpss_search_stub(self):
        self._check(P.gpss_search(cpc="G08B21/04", keyword="fall detection"))

    def test_epo_search_stub(self):
        self._check(P.epo_search(cql="ic=A61B5/024"))

    def test_gpatents_search_stub(self):
        self._check(P.gpatents_search(query="fall detection"))


if __name__ == "__main__":
    unittest.main()
