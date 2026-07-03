#!/usr/bin/env python3
"""search_audit.py — R13 landing plane: rigor gate over a search matrix-log.

Deterministic, stdlib-only, zero-network. Ports the container's search_audit
tool: reads a campaign's matrix-log.jsonl (one query per line) and scores search
breadth against floor thresholds, so a thin search cannot pass as a complete
landscape. Issues NO network requests — it only audits the evidence the search
agent left behind.

Usage:
  python3 search_audit.py --log path/to/matrix-log.jsonl [--campaign path/to/00_campaign.md]

Emits the verdict envelope as JSON (verdict PASS|WARN|FAIL, coverage, thresholds,
gaps, warnings, per_jurisdiction, per_database, applied_overrides, evidence).

All errors print a single-line typed JSON envelope + nonzero exit; no traceback
reaches stdout (R13.6).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import search_audit as _sa  # noqa: E402


class ScriptError(Exception):
    def __init__(self, code: str, message: str, **extra):
        self.code = code
        self.message = message
        self.extra = extra
        super().__init__(message)


def _fail(code: str, message: str, **extra) -> None:
    env = {"success": False, "error_code": code, "message": message}
    env.update(extra)
    sys.stdout.write(json.dumps(env, ensure_ascii=False) + "\n")
    sys.exit(2)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="search_audit.py",
        description="Rigor gate over a search matrix-log (R13 landing plane).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--log", dest="log_path", required=True, help="matrix-log.jsonl path")
    p.add_argument("--campaign", dest="campaign_path", default=None,
                   help="optional 00_campaign.md with threshold overrides")
    p.add_argument("--repo", default=None, help="repo root (unused; landing-plane convention)")
    args = p.parse_args(argv)

    if not Path(args.log_path).is_file():
        raise ScriptError("INPUT_NOT_FOUND", f"matrix-log not found: {args.log_path}")

    try:
        result = _sa.audit(args.log_path, args.campaign_path)
    except _sa.MatrixLogError as e:
        raise ScriptError(
            "MATRIX_LOG_UNPARSEABLE", str(e),
            hint="matrix-log.jsonl 必須存在且為每行一筆 JSON 查詢紀錄（schema 見 priorsearch.md §0）。",
        )
    result["success"] = True
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ScriptError as e:
        _fail(e.code, e.message, **e.extra)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        _fail("UNEXPECTED", f"{type(e).__name__}: {e}")
