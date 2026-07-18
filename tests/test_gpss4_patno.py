"""BR_20260718 regression: gpss4 patent-number extraction for TW grant numbers.

TW GRANT publication numbers are `TW` + kind letter (I/M/D) + digits — the
country code is followed by a THIRD letter before the digits, breaking the old
`[A-Z]{2}\\d{6,}` assumption shared across four regexes. This locks in the fixed
country segment (gpss4/patno.py) so:
  - TWI/TWM/TWD grant numbers are extracted WHOLE (not `WI...` with T eaten, not
    dropped to []).
  - TW publication numbers (TW + digits + A) and CN/US/EP/WO (kind code at tail)
    stay unaffected.

Run: uv run pytest tests/test_gpss4_patno.py -q
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from patent_mcp_server.gpss4.patno import (  # noqa: E402
    PAT_NO_RE,
    KINDED_RE,
    APPLYNO_RE,
    TW_NO_RE,
)


# (input, expected-whole-token) — BR §5 regression vectors.
_VECTORS = [
    ("TWI930018B", "TWI930018B"),      # invention grant (TWI), must not eat T / drop
    ("TWM683169U", "TWM683169U"),      # utility-model grant (TWM)
    ("TWD123456S", "TWD123456S"),      # design grant (TWD), if GPSS returns it
    ("TW201534271A", "TW201534271A"),  # TW publication (TW+digits), unaffected
    ("US20230081319A1", "US20230081319A1"),  # US kind code at tail, unaffected
    ("CN120543023A", "CN120543023A"),  # CN unaffected
]


class TestPatNoRe(unittest.TestCase):
    def test_findall_extracts_whole_token(self):
        for inp, exp in _VECTORS:
            with self.subTest(inp=inp):
                self.assertEqual(PAT_NO_RE.findall(inp), [exp])

    def test_no_phantom_t_eaten(self):
        # the exact 427-phantom-number bug: never emit WI.../WM... (T eaten).
        for inp in ("TWI930018B", "TWM683169U"):
            got = PAT_NO_RE.findall(inp)
            self.assertTrue(all(not g.startswith(("WI", "WM")) for g in got), got)

    def test_mid_token_guard_holds(self):
        # figure-image path: token embedded, tail NOT \b-anchored but leading
        # lookbehind must prevent a mid-token match.
        self.assertEqual(
            PAT_NO_RE.findall(".../0066/US20160373797A1_001.png"),
            ["US20160373797A1"],
        )


class TestKindedRe(unittest.TestCase):
    def test_grant_numbers_fullmatch(self):
        for inp in ("TWI930018B", "TWM683169U", "US20230081319A1"):
            with self.subTest(inp=inp):
                self.assertIsNotNone(KINDED_RE.fullmatch(inp))


class TestTwNoRe(unittest.TestCase):
    def test_findall_extracts_whole_token(self):
        for inp, exp in _VECTORS:
            with self.subTest(inp=inp):
                self.assertEqual(TW_NO_RE.findall(inp), [exp])


class TestApplyNoRe(unittest.TestCase):
    def test_dotted_and_bare_application_numbers(self):
        # apply_no forms must still match (dotted CN/TW + bare digits).
        self.assertIsNotNone(APPLYNO_RE.fullmatch("CN202411232691.8"))
        self.assertIsNotNone(APPLYNO_RE.fullmatch("US18351816"))
        self.assertIsNotNone(APPLYNO_RE.fullmatch("1234567"))


if __name__ == "__main__":
    unittest.main()
