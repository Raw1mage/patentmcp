"""
GPSS4 login CAPTCHA recognition — md5 lookup table.

Reverse-engineered mechanism (2026-07-11, design.md DD-3):
  - The login CAPTCHA is FIVE independent single-glyph GIFs served under a
    per-session ID directory: /gpss4/accserverusr/<ID-zero-padded>/n{0..4}.gif
  - Each glyph GIF is a STATIC font sprite: the same character always renders to
    byte-identical GIF (md5-stable) across sessions. The per-render `?<nonce>`
    query string is decorative (does not change the bytes).
  - The correct answer is bound to the SESSION SLOT (the ID in the URL / hidden
    field), NOT to the image bytes. The image just tells you which char each
    slot expects.

So recognition is a pure md5 -> char lookup: fetch the 5 glyph GIFs on the same
session, md5 each, look up the char. No image OCR, no ML, no tesseract.

The table is built once by human-labeling the distinct glyph sprites
(captcha_data/md5_table.json). An unknown md5 (a char never labeled) yields '?';
the login loop then retries with a fresh session (new glyphs) until all 5 map.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Dict, List, Optional, Tuple

_TABLE_PATH = os.path.join(os.path.dirname(__file__), "captcha_data", "md5_table.json")


class CaptchaTable:
    """md5(glyph GIF bytes) -> character lookup for the GPSS4 login CAPTCHA."""

    def __init__(self, table_path: str = _TABLE_PATH):
        self.table_path = table_path
        self._table: Dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.table_path):
            with open(self.table_path) as f:
                self._table = json.load(f)

    def ready(self) -> bool:
        return len(self._table) > 0

    def char_for(self, gif_bytes: bytes) -> Optional[str]:
        """Return the char for one glyph GIF, or None if the md5 is unknown."""
        return self._table.get(hashlib.md5(gif_bytes).hexdigest())

    def recognize(self, glyphs: List[bytes]) -> Tuple[str, List[str]]:
        """Map an ordered list of glyph GIF bytes -> (code, unknown_md5s).

        code contains '?' at each position whose md5 is not in the table;
        unknown_md5s lists those md5s so callers can report / extend the table.
        """
        code = ""
        unknown: List[str] = []
        for b in glyphs:
            m = hashlib.md5(b).hexdigest()
            ch = self._table.get(m)
            if ch is None:
                code += "?"
                unknown.append(m)
            else:
                code += ch
        return code, unknown

    def add(self, gif_bytes: bytes, char: str, persist: bool = True) -> None:
        """Teach the table one glyph -> char mapping (for filling gaps like 'Z')."""
        self._table[hashlib.md5(gif_bytes).hexdigest()] = char
        if persist:
            os.makedirs(os.path.dirname(self.table_path), exist_ok=True)
            with open(self.table_path, "w") as f:
                json.dump(self._table, f, indent=0)
