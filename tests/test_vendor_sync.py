"""test_vendor_sync.py — fail loud (PURE_LIB_DRIFT) if the vendored _lib copy
drifts from the src/_pure SSOT.

The landing scripts under skills/patentworks/scripts/ vendor a self-contained
copy of the deterministic pure logic (R13.6). That copy MUST stay byte-identical
to src/patent_mcp_server/_pure/ (and src/patent_mcp_server/search_audit.py).
Regenerate with: python3 scripts/sync_pure_lib.py
"""
from __future__ import annotations

import hashlib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC_PURE = REPO / "src" / "patent_mcp_server" / "_pure"
SRC_AUDIT = REPO / "src" / "patent_mcp_server" / "search_audit.py"
VENDOR = REPO / "skills" / "patentworks" / "scripts" / "_lib"

PAIRS = [
    (SRC_PURE / "screening.py", VENDOR / "screening.py"),
    (SRC_PURE / "claims.py", VENDOR / "claims.py"),
    (SRC_AUDIT, VENDOR / "search_audit.py"),
]


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_vendored_lib_matches_src_pure():
    for src, dst in PAIRS:
        assert src.is_file(), f"PURE_LIB_DRIFT: source missing {src}"
        assert dst.is_file(), f"PURE_LIB_DRIFT: vendored copy missing {dst} — run scripts/sync_pure_lib.py"
        s, d = _sha(src), _sha(dst)
        assert s == d, (
            f"PURE_LIB_DRIFT: {dst.relative_to(REPO)} out of sync with "
            f"{src.relative_to(REPO)} ({s[:12]} != {d[:12]}); run scripts/sync_pure_lib.py"
        )
