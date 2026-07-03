#!/usr/bin/env python3
"""claims_tools.py — R13 landing plane: pure claim/HTML text transforms.

Deterministic, stdlib-only, zero-network. Wraps the same clean_html_text /
extract_claim1_text logic the container uses, so the agent can re-split or clean
claim text locally from any fetched text.

Subcommands:
  clean-html      strip HTML tags + normalize whitespace
  extract-claim1  pull claim 1 out of a claims block (--full/--no-full)
  claim1-empty    report whether a claim1 string is substantively empty (boilerplate/blank)

Input: --in <file> (UTF-8 text) OR stdin when --in is omitted.

Usage:
  python3 claims_tools.py clean-html --in claims.html
  echo "1. A method ... 2. The method ..." | python3 claims_tools.py extract-claim1 --no-full
  python3 claims_tools.py claim1-empty --in c1.txt

All errors print a single-line typed JSON envelope to stdout + nonzero exit;
no traceback reaches stdout (R13.6).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import clean_html_text, extract_claim1_text  # noqa: E402
from _lib.screening import _claim1_is_empty  # noqa: E402


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


def _read_text(in_path) -> str:
    if in_path:
        p = Path(in_path)
        if not p.is_file():
            raise ScriptError("INPUT_NOT_FOUND", f"input file not found: {p}")
        return p.read_text(encoding="utf-8")
    return sys.stdin.read()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="claims_tools.py",
        description="Pure claim/HTML text transforms (R13 landing plane).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--repo", default=None, help="repo root (unused; landing-plane convention)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp1 = sub.add_parser("clean-html", help="strip HTML tags + normalize whitespace")
    sp1.add_argument("--in", dest="in_path", default=None, help="input file (else stdin)")

    sp2 = sub.add_parser("extract-claim1", help="extract claim 1 from a claims block")
    sp2.add_argument("--in", dest="in_path", default=None, help="input file (else stdin)")
    sp2.add_argument("--full", dest="full", action="store_true", default=True,
                     help="return full claim text (default)")
    sp2.add_argument("--no-full", dest="full", action="store_false",
                     help="truncate to 1000 chars")

    sp3 = sub.add_parser("claim1-empty", help="report if claim1 is substantively empty")
    sp3.add_argument("--in", dest="in_path", default=None, help="input file (else stdin)")

    args = p.parse_args(argv)
    text = _read_text(args.in_path)

    if args.cmd == "clean-html":
        out = clean_html_text(text)
        sys.stdout.write(json.dumps({"success": True, "cmd": "clean-html", "text": out},
                                    ensure_ascii=False) + "\n")
    elif args.cmd == "extract-claim1":
        out = extract_claim1_text(text, full=args.full)
        sys.stdout.write(json.dumps({"success": True, "cmd": "extract-claim1",
                                     "full": args.full, "claim1": out},
                                    ensure_ascii=False) + "\n")
    elif args.cmd == "claim1-empty":
        empty = _claim1_is_empty(text.strip())
        sys.stdout.write(json.dumps({"success": True, "cmd": "claim1-empty", "empty": empty},
                                    ensure_ascii=False) + "\n")
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
