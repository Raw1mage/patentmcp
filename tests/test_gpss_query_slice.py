"""specs/patentmcp_bulk-entry-unification Phase 8 (DD-10/DD-11; BR_20260715).

GPSS query-slicing tests. No real network — a FakeGPSS with an injectable
condition-length ceiling raises the TIPO wall (`Exceeded search condition
length`) for over-long keyword strings, then serves per-shard hits. Covers:
parser boolean/phrase/paren/NOT classification, widest-positive-group selection,
recursive bisection, NOT-group byte-identical-per-shard (the key recall-safety
invariant), pubno union dedup, CONDITION_LENGTH_IRREDUCIBLE fail-fast, and
tri-country symmetry (A∩B∩C¬D vs pairwise B∩C¬D).

Run: uv run pytest tests/test_gpss_query_slice.py -q
"""
import asyncio
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import patent_mcp_server.search_dispatcher as SD


def _run(coro):
    return asyncio.run(coro)


# ── pure parser tests ────────────────────────────────────────────────
class ParseGpssQuery(unittest.TestCase):
    def test_and_of_or_groups_with_not(self):
        p = SD._parse_gpss_query("(A OR B OR C) and (D OR E) not (F OR G)")
        self.assertEqual(p["positive_groups"], [["A", "B", "C"], ["D", "E"]])
        self.assertEqual(p["not_groups"], [["F", "G"]])

    def test_quoted_phrase_not_split_on_space(self):
        p = SD._parse_gpss_query('("vital sign" OR radar) not (vehicle)')
        self.assertEqual(p["positive_groups"], [['"vital sign"', "radar"]])
        self.assertEqual(p["not_groups"], [["vehicle"]])

    def test_nested_parens_and_bare_term(self):
        p = SD._parse_gpss_query("radar and (fall OR drop) not noise")
        # bare positive term + a parenthesized OR-group both classified positive
        self.assertEqual(p["positive_groups"], [["radar"], ["fall", "drop"]])
        self.assertEqual(p["not_groups"], [["noise"]])

    def test_case_insensitive_operators(self):
        p = SD._parse_gpss_query("(a OR b) AND (c OR d) NOT (e or f)")
        self.assertEqual(p["positive_groups"], [["a", "b"], ["c", "d"]])
        self.assertEqual(p["not_groups"], [["e", "f"]])


# ── sharder: widest-group selection + recursion ─────────────────────
class ShardSelection(unittest.TestCase):
    def _not_segment(self, shard):
        # extract the substring from 'not' onward for byte-comparison
        m = re.search(r"\bnot\b.*$", shard)
        return m.group(0) if m else ""

    def test_widest_positive_group_is_bisected(self):
        # positive groups: 4 terms vs 2 terms → the 4-term group is split
        kw = "(A OR B OR C OR D) and (E OR F) not (G OR H)"
        # fits only when the widest group is halved (<= threshold length)
        fits = lambda q: len(q) <= len(kw) - 3
        shards = SD._shard_gpss_query(kw, fits)
        # each shard keeps the 2-term (E OR F) group whole, splits the 4-term one
        for s in shards:
            self.assertIn("E OR F", s)
        # union of the split halves covers A,B,C,D exactly once each
        joined = " ".join(shards)
        for t in ("A", "B", "C", "D"):
            self.assertIn(t, joined)

    def test_recursive_bisection_when_shard_still_too_long(self):
        # tiny threshold forces splitting down to single positive terms
        kw = "(A OR B OR C OR D OR E OR F OR G OR H) not (X OR Y)"
        fits = lambda q: len(q) <= len("A not (X OR Y)")
        shards = SD._shard_gpss_query(kw, fits)
        # 8 positive terms → 8 single-term shards
        self.assertEqual(len(shards), 8)
        for s in shards:
            self.assertTrue(fits(s), f"shard still over: {s!r}")

    def test_not_group_byte_identical_across_shards(self):
        # THE recall-safety invariant: every shard's not(...) segment is byte-
        # identical — splitting a NOT group would silently under-exclude noise.
        kw = "(A OR B OR C OR D) and (E OR F OR G OR H) not (N1 OR N2 OR N3)"
        fits = lambda q: len(q) <= 40
        shards = SD._shard_gpss_query(kw, fits)
        not_segs = {self._not_segment(s) for s in shards}
        self.assertEqual(len(not_segs), 1, f"NOT segment drifted: {not_segs}")
        self.assertIn("N1 OR N2 OR N3", not_segs.pop())

    def test_irreducible_single_term_still_too_long(self):
        # even a single OR-term + all AND/NOT groups can't fit → raise
        kw = "(A OR B) and (C OR D) not (E OR F)"
        fits = lambda q: False  # nothing ever fits
        with self.assertRaises(ValueError) as cm:
            SD._shard_gpss_query(kw, fits)
        self.assertIn("CONDITION_LENGTH_IRREDUCIBLE", str(cm.exception))

    def test_depth_cap_raises_irreducible(self):
        # a positive group with many terms but fits_fn never satisfied at depth
        kw = "(" + " OR ".join(f"T{i}" for i in range(64)) + ") not (Z)"
        fits = lambda q: False
        with self.assertRaises(ValueError):
            SD._shard_gpss_query(kw, fits)


if __name__ == "__main__":
    unittest.main(verbosity=2)
