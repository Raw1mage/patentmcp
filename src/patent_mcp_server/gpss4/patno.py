"""Shared patent-number token patterns for GPSS4 web scraping (BR_20260718).

Root cause the shared module fixes: four separate regexes across adv_search.py
and folder.py each hard-coded a `[A-Z]{2}\\d{6,}` country segment, assuming a
2-letter ISO country code is immediately followed by digits. TW GRANT
publication numbers break that assumption: they are `TW` + a kind letter
(`I`=invention / `M`=utility model / `D`=design) + digits, i.e. the country code
is followed by a THIRD letter before the digits.

Two failure modes resulted, both wrong:
- Without a leading lookbehind, the engine backtracked and matched from the `W`
  of `TWI930018B`, emitting `WI930018B` — a number that exists in no patent
  office (polluted the pool with 427 phantom numbers).
- With the `(?<![A-Z0-9])` guard added by BR_20260716, the same input matched
  NOTHING (`[]`) — silent under-extraction.

Fix (BR §5, verified against TWI930018B / TWM683169U / TW201534271A /
US20230081319A1 / CN120543023A): make the country segment accept a `TW[IMD]`
3-letter grant prefix, else a generic 2-letter country code. TW PUBLICATION
numbers (`TW` + digits + `A`) and CN/US/EP/WO (kind code at the tail) are
unaffected — their country code is still followed directly by digits.

All four call sites import from here so the country-segment assumption lives in
ONE place (BR §7.2, prevents the isomorphic recurrence).
"""
import re

# The country segment: a TW grant prefix (TW + kind letter I/M/D) takes
# priority, otherwise a generic 2-letter ISO country code. Ordering matters —
# `TW[IMD]` must be tried before `[A-Z]{2}` so `TWI...` is not consumed as
# country `TW` + a stray `I`.
_CC = r'(?:TW[IMD]|[A-Z]{2})'

# A patent-number-looking token: country segment + 6+ digits + optional kind
# code (letter + optional digit). The leading (?<![A-Z0-9]) avoids matching
# mid-token (e.g. inside a figure-image path `.../US20160373797A1_001.png`),
# and the tail is intentionally NOT anchored with \b (A1 is followed by `_`,
# both \w -> no boundary).
PAT_NO_RE = re.compile(r'(?<![A-Z0-9])(' + _CC + r'\d{6,}(?:[A-Z]\d?)?)')

# A country-prefixed token that ENDS in a kind code (letter[+optional digit]) at
# token end — used to pick pat_no out of a cell that fullmatch-es this shape.
KINDED_RE = re.compile(r'^' + _CC + r'\d{6,}[A-Z]\d?$')

# apply_no candidates: country+digits w/o kind code, OR dotted CN/TW application
# numbers, OR a bare all-digit case number (>=7 digits).
APPLYNO_RE = re.compile(
    r'^(?:' + _CC + r'\d{6,}(?:\.\d+)?|\d{7,}(?:\.\d+)?)$')

# mark-list table rows: patent-number tokens (folder.py). Same country segment;
# \b boundaries here are safe (folder cells are not figure paths).
TW_NO_RE = re.compile(r'\b(' + _CC + r'\d{6,}[A-Z]?\d?)\b')
