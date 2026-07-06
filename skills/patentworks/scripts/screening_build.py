#!/usr/bin/env python3
"""screening_build.py — R13 landing plane: build a screening CSV from search records.

Runs on the host under the agent's own uid (R13.3). Deterministic, stdlib-only,
zero-network: takes a records JSON (already fetched by the container's
patent_search / search tools) and produces the human-readable screening CSV that
build_screening_table used to build inside the container.

Pipeline: (optional adapter) → dedup_by_family → resolve_columns → build_csv.

Usage:
  python3 screening_build.py --in records.json --out out.csv \\
      [--purpose landscape|minimal|priorart|fto] \\
      [--extra cpc,ipc] [--exclude legal_status] \\
      [--source records|gpss|google|ppubs|epo]

Input shapes (--in):
  * {"records": [ {..}, .. ]}   — the PatentSearchEnvelope shape (default source=records)
  * [ {..}, .. ]                — a bare records list
  * a raw source payload        — when --source is gpss/google/ppubs/epo, the
                                  matching adapter normalizes it first:
                                    gpss   → gpss_to_records(dict)
                                    google → google_to_records(list)
                                    ppubs  → ppubs_to_records(dict)
                                    epo    → epo_biblio_to_record(pub, dict) per item
                                             (input: {"pub": ..., "biblio": {..}} list)

All errors print a single-line typed JSON envelope to stdout and exit nonzero;
no traceback ever reaches stdout (R13.6).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import (  # noqa: E402
    build_csv,
    dedup_by_family,
    epo_biblio_to_record,
    google_to_records,
    gpss_to_records,
    ppubs_to_records,
    resolve_columns,
)


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


def _load_records(raw: object, source: str) -> list:
    """Normalize the parsed --in payload into a list of record dicts."""
    if source == "records":
        if isinstance(raw, dict):
            recs = raw.get("records")
            if recs is None:
                raise ScriptError(
                    "BAD_INPUT",
                    "records-source JSON object has no 'records' key; pass a bare list "
                    "or {\"records\": [...]}, or set --source to a raw adapter",
                )
            return list(recs)
        if isinstance(raw, list):
            return list(raw)
        raise ScriptError("BAD_INPUT", f"records-source expects an object or list, got {type(raw).__name__}")

    if source == "gpss":
        if not isinstance(raw, dict):
            raise ScriptError("BAD_INPUT", "gpss source expects a JSON object (GPSS search JSON)")
        return gpss_to_records(raw)
    if source == "google":
        if not isinstance(raw, list):
            raise ScriptError("BAD_INPUT", "google source expects a JSON list (gpatents_search results)")
        return google_to_records(raw)
    if source == "ppubs":
        if not isinstance(raw, dict):
            raise ScriptError("BAD_INPUT", "ppubs source expects a JSON object (PPUBS run_query result)")
        return ppubs_to_records(raw)
    if source == "epo":
        if not isinstance(raw, list):
            raise ScriptError(
                "BAD_INPUT",
                "epo source expects a JSON list of {\"pub\": str, \"biblio\": {..}} items",
            )
        out = []
        for i, item in enumerate(raw):
            if not isinstance(item, dict) or "pub" not in item or "biblio" not in item:
                raise ScriptError("BAD_INPUT", f"epo item {i} must be {{'pub':..,'biblio':..}}")
            out.append(epo_biblio_to_record(item["pub"], item["biblio"]))
        return out

    raise ScriptError("BAD_INPUT", f"unknown --source {source!r}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="screening_build.py",
        description="Build a screening CSV from search records (R13 landing plane).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--in", dest="in_path", required=True, help="input records JSON path")
    p.add_argument("--out", dest="out_path", required=True, help="output CSV path")
    p.add_argument("--purpose", default="landscape",
                   help="column preset: landscape|minimal|priorart|fto (default landscape)")
    p.add_argument("--extra", default="", help="comma-separated extra column keys to include")
    p.add_argument("--exclude", default="", help="comma-separated selectable column keys to drop")
    p.add_argument("--source", default="records",
                   choices=["records", "gpss", "google", "ppubs", "epo"],
                   help="input normalization source (default records = already normalized)")
    p.add_argument("--repo", default=None, help="repo root (sets patentdb absorb target)")
    p.add_argument("--no-absorb", action="store_true",
                   help="skip the patentdb inline-absorb side-effect")
    args = p.parse_args(argv)

    in_path = Path(args.in_path)
    if not in_path.is_file():
        raise ScriptError("INPUT_NOT_FOUND", f"input file not found: {in_path}")
    try:
        raw = json.loads(in_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ScriptError("BAD_JSON", f"could not parse --in as JSON: {e}")

    records = _load_records(raw, args.source)
    extra = [x.strip() for x in args.extra.split(",") if x.strip()]
    exclude = [x.strip() for x in args.exclude.split(",") if x.strip()]

    deduped = dedup_by_family(records)
    columns = resolve_columns(purpose=args.purpose, extra=extra, exclude=exclude)
    csv_bytes = build_csv(deduped, columns)

    out_path = Path(args.out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(csv_bytes)

    # patentdb inline-absorb (DD-11): the records are already in memory when the
    # CSV lands, so absorbing bibliographic rows into the global store costs zero
    # extra network. Never blocks the CSV output; result is reported for audit.
    absorb: dict | None = None
    if not args.no_absorb:
        try:
            import patentdb_local as _pdb  # noqa: E402 — sibling landing script
            # default absorb target = this repo's patentdb (scripts live at
            # <repo>/skills/patentworks/scripts — 3 parents up), NOT cwd.
            repo_root = args.repo or str(Path(__file__).resolve().parents[3])
            db_path = _pdb._default_db(repo_root)
            conn = _pdb._connect(db_path)
            try:
                created = updated = skipped = 0
                for rec in deduped:
                    pub_raw = (rec.get("pubno") or "").strip()
                    if not pub_raw:
                        skipped += 1
                        continue
                    fields = {col: rec[rk] for rk, col in _pdb._RECORD_FIELD_MAP.items()
                              if rec.get(rk) not in (None, "", [])}
                    res = _pdb.put(conn, pub_raw, fields=fields, acquisition_cost="low")
                    if res["action"] == "created":
                        created += 1
                    elif res["action"] == "updated":
                        updated += 1
                    else:
                        skipped += 1
            finally:
                conn.close()
            absorb = {"imported": created, "updated": updated,
                      "skipped": skipped, "db": str(db_path)}
        except Exception as e:  # noqa: BLE001 — absorb must never break the CSV
            absorb = {"error": "absorb_failed", "detail": f"{type(e).__name__}: {e}"}

    sys.stdout.write(json.dumps({
        "success": True,
        "out": str(out_path),
        "rows": len(deduped),
        "columns": columns,
        "bytes": len(csv_bytes),
        "patentdb_absorb": absorb,
    }, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ScriptError as e:
        _fail(e.code, e.message, **e.extra)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 — no traceback to stdout (R13.6)
        _fail("UNEXPECTED", f"{type(e).__name__}: {e}")
