"""plans/patentmcp_bulk-entry-unification TV-5: _keyword_to_cql contract lock.

Boolean / quoted-phrase / parenthesized / NOT translation from GPSS-style
keyword expressions into EPO CQL, per DD-6 (current behavior IS the contract).
No network. Run: uv run pytest tests/test_keyword_to_cql.py -q
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from patent_mcp_server.search_dispatcher import _keyword_to_cql


class KeywordToCql(unittest.TestCase):
    # ── TV-5: four canonical cases, byte-for-byte expected outputs ──
    def test_boolean_and(self):
        self.assertEqual(
            _keyword_to_cql("radar AND fall"),
            "txt=radar and txt=fall",
        )

    def test_quoted_phrase_or(self):
        self.assertEqual(
            _keyword_to_cql('"millimeter wave" OR radar'),
            'txt="millimeter wave" or txt=radar',
        )

    def test_parenthesized(self):
        self.assertEqual(
            _keyword_to_cql("(radar OR lidar) AND fall"),
            "(txt=radar or txt=lidar) and txt=fall",
        )

    def test_not(self):
        self.assertEqual(
            _keyword_to_cql("radar NOT vehicle"),
            "txt=radar not txt=vehicle",
        )

    # ── edge cases ──
    def test_empty_string(self):
        self.assertEqual(_keyword_to_cql(""), "")

    def test_pure_phrase(self):
        self.assertEqual(
            _keyword_to_cql('"vital sign"'),
            'txt="vital sign"',
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
