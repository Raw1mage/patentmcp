#!/usr/bin/env python3
"""sync_pure_lib.py — regenerate the vendored _pure copy for landing scripts.

The landing scripts under skills/patentworks/scripts/ must be self-contained
(R13.6): they cannot import from src/. So the deterministic pure logic lives at
src/patent_mcp_server/_pure/ (the container's SSOT) and is VENDORED into
skills/patentworks/scripts/_lib/. This script copies the _pure modules into the
vendored dir verbatim.

Drift between the two copies is caught by tests/test_vendor_sync.py (error
PURE_LIB_DRIFT). Run this whenever src/patent_mcp_server/_pure/ changes.

The _lib/__init__.py and _lib/search_audit.py are managed separately:
  * __init__.py is the vendored-copy's own package header (hand-maintained).
  * search_audit.py is vendored from src/patent_mcp_server/search_audit.py.

Usage: python3 scripts/sync_pure_lib.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC_PURE = REPO / "src" / "patent_mcp_server" / "_pure"
SRC_AUDIT = REPO / "src" / "patent_mcp_server" / "search_audit.py"
VENDOR = REPO / "skills" / "patentworks" / "scripts" / "_lib"

# (source, dest) pairs kept in lock-step with the vendored copy.
PAIRS = [
    (SRC_PURE / "screening.py", VENDOR / "screening.py"),
    (SRC_PURE / "claims.py", VENDOR / "claims.py"),
    (SRC_AUDIT, VENDOR / "search_audit.py"),
]


def main() -> int:
    VENDOR.mkdir(parents=True, exist_ok=True)
    for src, dst in PAIRS:
        if not src.is_file():
            print(f"error: source missing: {src}", file=sys.stderr)
            return 2
        shutil.copyfile(src, dst)
        print(f"synced {src.relative_to(REPO)} -> {dst.relative_to(REPO)}")
    print("done. (_lib/__init__.py is hand-maintained, not synced)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
