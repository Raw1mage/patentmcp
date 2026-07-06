#!/usr/bin/env python3
"""patentdb_local.py — R13 landing plane: local patentdb bibliographic store ops.

Runs on the host under the agent's own uid, operating a local sqlite bibliographic
store directly (no container, no token round-trip). Self-contained: vendors the
progressive-merge upsert / FTS query / CSV import logic (R13.6 — no import from
src/).

Subcommands:
  put         upsert one patent's bibliographic fields (--pubno, --fields JSON)
  query       lookup (--pubno) | full-text (--fts) | country (--country); --limit
  import-csv  bulk-import bibliographic columns from a candidates.csv (--csv)

Store: sqlite at --db (default <repo>/patentdb/patentdb.sqlite; --repo sets the
default parent).

Usage:
  python3 patentdb_local.py put --pubno US20230081319A1 --fields '{"title_orig":"..."}'
  python3 patentdb_local.py query --fts escrow --limit 10
  python3 patentdb_local.py import-csv --csv candidates.csv

All errors print a single-line typed JSON envelope + nonzero exit; no traceback
reaches stdout (R13.6).
"""
from __future__ import annotations

import argparse
import csv as _csv
import json
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


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


# ── pubno normalization (vendored from patentdb_store.py) ─────────────

def normalize_pubno(publication_number: str) -> Tuple[str, str]:
    pat = re.sub(r"[\s/\-,\.]+", "", publication_number or "").upper()
    country = "US"
    if pat.startswith("TW"):
        country, pat = "TW", pat[2:]
    elif pat.startswith("US"):
        country, pat = "US", pat[2:]
    elif pat.startswith("EP"):
        country, pat = "EP", pat[2:]
    elif pat.startswith("WO"):
        country, pat = "WO", pat[2:]
    elif pat.startswith("CN"):
        country, pat = "CN", pat[2:]
    elif re.match(r"^[IMD]\d+", pat):
        country = "TW"
    elif re.match(r"^\d{9}$", pat):
        country = "TW"
    m_cert = re.match(r"^([IMD]\d+)[A-Za-z]*$", pat)
    if m_cert:
        pat = m_cert.group(1)
    else:
        m_app = re.match(r"^(\d+)[A-Za-z]*$", pat)
        if m_app:
            pat = m_app.group(1)
    return country, pat


def canonical_pubno(publication_number: str) -> str:
    country, norm = normalize_pubno(publication_number)
    return f"{country}{norm}"


_TEXT_COLS = [
    "country", "normalized_no", "kind", "title_orig", "title_en", "abstract",
    "claim1", "applicants", "inventors", "application_no", "application_date",
    "publication_date", "priority_date", "cpc_codes", "ipc_codes", "family_id",
    "pdf_path", "pdf_sha256", "xml_path", "xml_sha256", "figures_json",
    "first_source", "acquisition_cost", "created_at", "updated_at",
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS patents (
  pubno TEXT PRIMARY KEY, country TEXT NOT NULL, normalized_no TEXT NOT NULL,
  kind TEXT, title_orig TEXT, title_en TEXT, abstract TEXT, claim1 TEXT,
  applicants TEXT, inventors TEXT, application_no TEXT, application_date TEXT,
  publication_date TEXT, priority_date TEXT, cpc_codes TEXT, ipc_codes TEXT,
  family_id TEXT, pdf_path TEXT, pdf_sha256 TEXT, xml_path TEXT, xml_sha256 TEXT,
  figures_json TEXT, first_source TEXT, acquisition_cost TEXT,
  scraping_used INTEGER DEFAULT 0, created_at TEXT, updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_patents_country  ON patents(country);
CREATE INDEX IF NOT EXISTS idx_patents_family   ON patents(family_id);
CREATE INDEX IF NOT EXISTS idx_patents_appdate  ON patents(application_date);
CREATE INDEX IF NOT EXISTS idx_patents_acq_cost ON patents(acquisition_cost);
CREATE VIRTUAL TABLE IF NOT EXISTS patents_fts USING fts5(
  pubno UNINDEXED, title_orig, title_en, abstract, claim1,
  content='patents', content_rowid='rowid', tokenize='trigram'
);
CREATE TRIGGER IF NOT EXISTS patents_ai AFTER INSERT ON patents BEGIN
  INSERT INTO patents_fts(rowid, pubno, title_orig, title_en, abstract, claim1)
  VALUES (new.rowid, new.pubno, new.title_orig, new.title_en, new.abstract, new.claim1);
END;
CREATE TRIGGER IF NOT EXISTS patents_ad AFTER DELETE ON patents BEGIN
  INSERT INTO patents_fts(patents_fts, rowid, pubno, title_orig, title_en, abstract, claim1)
  VALUES ('delete', old.rowid, old.pubno, old.title_orig, old.title_en, old.abstract, old.claim1);
END;
CREATE TRIGGER IF NOT EXISTS patents_au AFTER UPDATE ON patents BEGIN
  INSERT INTO patents_fts(patents_fts, rowid, pubno, title_orig, title_en, abstract, claim1)
  VALUES ('delete', old.rowid, old.pubno, old.title_orig, old.title_en, old.abstract, old.claim1);
  INSERT INTO patents_fts(rowid, pubno, title_orig, title_en, abstract, claim1)
  VALUES (new.rowid, new.pubno, new.title_orig, new.title_en, new.abstract, new.claim1);
END;
"""

_JSON_COLS = {"applicants", "inventors", "cpc_codes", "ipc_codes", "figures_json"}
_COMPLETENESS_FIELDS = ["title_orig", "abstract", "claim1", "cpc_codes", "family_id"]
_COMPLETENESS_BLOBS = ["pdf_path", "xml_path", "figures_json"]


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    return conn


def _maybe_json(v: Any) -> Any:
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return v


def _completeness(row: Dict[str, Any]) -> Dict[str, bool]:
    flags = {}
    for f in _COMPLETENESS_FIELDS + _COMPLETENESS_BLOBS:
        v = row.get(f)
        flags[f] = bool(v and str(v).strip() and v not in ("[]", "{}"))
    flags["title"] = bool(
        (row.get("title_orig") and str(row.get("title_orig")).strip())
        or (row.get("title_en") and str(row.get("title_en")).strip())
    )
    return flags


def _public_row(row: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for k, v in row.items():
        if k == "rowid":
            continue
        if k in _JSON_COLS and v:
            try:
                out[k] = json.loads(v)
                continue
            except Exception:
                pass
        out[k] = v
    return out


def put(conn: sqlite3.Connection, publication_number: str, fields: Optional[Dict[str, Any]] = None,
        acquisition_cost: Optional[str] = None, overwrite: bool = False) -> Dict[str, Any]:
    pubno = canonical_pubno(publication_number)
    country, norm = normalize_pubno(publication_number)
    now = time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
    incoming: Dict[str, Any] = {}
    for k in _TEXT_COLS:
        if fields and k in fields and fields[k] not in (None, ""):
            incoming[k] = _maybe_json(fields[k])
    if acquisition_cost:
        incoming["acquisition_cost"] = acquisition_cost
    incoming["country"] = country
    incoming["normalized_no"] = norm

    existing = conn.execute("SELECT * FROM patents WHERE pubno=?", (pubno,)).fetchone()
    if existing is None:
        cols = ["pubno", "created_at", "updated_at"] + list(incoming.keys())
        vals = [pubno, now, now] + list(incoming.values())
        conn.execute(f"INSERT INTO patents ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)
        conn.commit()
        row = dict(conn.execute("SELECT * FROM patents WHERE pubno=?", (pubno,)).fetchone())
        return {"pubno": pubno, "action": "created", "completeness": _completeness(row)}

    ex = dict(existing)
    updates: Dict[str, Any] = {}
    for k, v in incoming.items():
        if k in ("country", "normalized_no"):
            continue
        cur = ex.get(k)
        if overwrite or cur is None or str(cur).strip() == "":
            if v not in (None, ""):
                updates[k] = v
    if updates:
        updates["updated_at"] = now
        set_clause = ",".join(f"{k}=?" for k in updates)
        conn.execute(f"UPDATE patents SET {set_clause} WHERE pubno=?", list(updates.values()) + [pubno])
        conn.commit()
    row = dict(conn.execute("SELECT * FROM patents WHERE pubno=?", (pubno,)).fetchone())
    return {"pubno": pubno, "action": "updated" if updates else "unchanged",
            "merged_fields": [k for k in updates if k != "updated_at"],
            "completeness": _completeness(row)}


def query(conn: sqlite3.Connection, publication_number=None, fts=None, country=None, limit=20) -> Dict[str, Any]:
    if publication_number:
        pubno = canonical_pubno(publication_number)
        r = conn.execute("SELECT * FROM patents WHERE pubno=?", (pubno,)).fetchone()
        if r is None:
            return {"found": False, "pubno": pubno}
        row = dict(r)
        return {"found": True, "patent": _public_row(row), "completeness": _completeness(row)}
    if fts:
        term = fts.strip()
        if len(term) >= 3:
            rows = conn.execute(
                """SELECT p.*, bm25(patents_fts) AS rank FROM patents_fts
                   JOIN patents p ON p.rowid = patents_fts.rowid
                   WHERE patents_fts MATCH ? ORDER BY rank LIMIT ?""", (term, limit)).fetchall()
            mode = "fts5"
        else:
            like = f"%{term}%"
            rows = conn.execute(
                """SELECT *, 0 AS rank FROM patents
                   WHERE title_orig LIKE ? OR title_en LIKE ? OR abstract LIKE ? OR claim1 LIKE ?
                   ORDER BY updated_at DESC LIMIT ?""", (like, like, like, like, limit)).fetchall()
            mode = "like_short"
        return {"count": len(rows), "match_mode": mode,
                "results": [{**_public_row(dict(r)), "rank": r["rank"],
                             "completeness": _completeness(dict(r))} for r in rows]}
    if country:
        rows = conn.execute("SELECT * FROM patents WHERE country=? ORDER BY updated_at DESC LIMIT ?",
                            (country.upper(), limit)).fetchall()
        return {"count": len(rows), "results": [_public_row(dict(r)) for r in rows]}
    rows = conn.execute("SELECT * FROM patents ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
    total = conn.execute("SELECT COUNT(*) c FROM patents").fetchone()["c"]
    return {"count": len(rows), "total": total, "results": [_public_row(dict(r)) for r in rows]}


# record-dict keys (unified screening record schema, _lib/screening.py) -> patentdb columns.
# Mirrors src/patent_mcp_server/patentdb_store.py _RECORD_FIELD_MAP — keep in sync.
_RECORD_FIELD_MAP = {
    "title": "title_orig",
    "abstract": "abstract",
    "claim1": "claim1",
    "appno": "application_no",
    "family_id": "family_id",
    "cpc": "cpc_codes",
    "ipc": "ipc_codes",
    "prio_date": "priority_date",
    "app_date": "application_date",
    "pub_date": "publication_date",
    "assignee": "applicants",
    "inventor": "inventors",
}

_CSV_HEADER_MAP = {
    "專利號": "pubno", "公開號": "pubno", "公告號": "pubno", "代表專利號": "pubno",
    "名稱": "title_orig", "標題": "title_orig", "摘要": "abstract",
    "獨立項": "claim1", "Claim1": "claim1", "申請號": "application_no", "家族": "family_id",
    "優先權日": "priority_date", "優先權": "priority_date", "申請日": "application_date",
    "公開/公告日": "publication_date", "公開日": "publication_date", "公告日": "publication_date",
    "CPC": "cpc_codes", "推測CPC": "cpc_codes",
    "IPC": "ipc_codes", "申請人": "applicants",
}


def import_csv(conn: sqlite3.Connection, csv_path: str) -> Dict[str, Any]:
    path = Path(csv_path)
    if not path.is_file():
        raise ScriptError("INPUT_NOT_FOUND", f"csv not found: {path}")
    created = updated = skipped = 0
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = _csv.DictReader(fh)
        headers = reader.fieldnames or []
        col_for = {h: _CSV_HEADER_MAP[(h or "").strip()] for h in headers
                   if (h or "").strip() in _CSV_HEADER_MAP}
        conn.execute("BEGIN")
        for rec in reader:
            pub_raw = (rec.get("專利號") or rec.get("公開號") or rec.get("公告號")
                       or rec.get("代表專利號") or rec.get("pubno") or "").strip()
            if not pub_raw:
                skipped += 1
                continue
            fields: Dict[str, Any] = {}
            for h, col in col_for.items():
                if col == "pubno":
                    continue
                val = (rec.get(h) or "").strip()
                if val:
                    fields[col] = val
            res = put(conn, pub_raw, fields=fields, acquisition_cost="low")
            if res["action"] == "created":
                created += 1
            elif res["action"] == "updated":
                updated += 1
            else:
                skipped += 1
        conn.commit()
    return {"imported": created, "updated": updated, "skipped": skipped, "csv": str(path)}


def _default_db(repo: Optional[str]) -> Path:
    if repo:
        return Path(repo) / "patentdb" / "patentdb.sqlite"
    return Path.cwd() / "patentdb" / "patentdb.sqlite"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="patentdb_local.py",
        description="Local patentdb bibliographic store ops (R13 landing plane).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--repo", default=None, help="repo root (sets default --db parent)")
    p.add_argument("--db", default=None, help="sqlite path (default <repo>/patentdb/patentdb.sqlite)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp_put = sub.add_parser("put", help="upsert one patent's bibliographic fields")
    sp_put.add_argument("--pubno", required=True)
    sp_put.add_argument("--fields", default="{}", help="JSON object of bibliographic fields")
    sp_put.add_argument("--acquisition-cost", default=None, help="high|low|free")
    sp_put.add_argument("--overwrite", action="store_true")

    sp_q = sub.add_parser("query", help="lookup / fts / country")
    sp_q.add_argument("--pubno", default=None)
    sp_q.add_argument("--fts", default=None)
    sp_q.add_argument("--country", default=None)
    sp_q.add_argument("--limit", type=int, default=20)

    sp_imp = sub.add_parser("import-csv", help="bulk import bibliographic columns")
    sp_imp.add_argument("--csv", dest="csv_path", required=True)

    args = p.parse_args(argv)
    db_path = Path(args.db) if args.db else _default_db(args.repo)
    conn = _connect(db_path)
    try:
        if args.cmd == "put":
            try:
                fields = json.loads(args.fields)
            except json.JSONDecodeError as e:
                raise ScriptError("BAD_JSON", f"--fields is not valid JSON: {e}")
            if not isinstance(fields, dict):
                raise ScriptError("BAD_INPUT", "--fields must be a JSON object")
            res = put(conn, args.pubno, fields=fields,
                      acquisition_cost=args.acquisition_cost, overwrite=args.overwrite)
        elif args.cmd == "query":
            res = query(conn, publication_number=args.pubno, fts=args.fts,
                        country=args.country, limit=args.limit)
        elif args.cmd == "import-csv":
            res = import_csv(conn, args.csv_path)
        else:
            raise ScriptError("BAD_INPUT", f"unknown cmd {args.cmd!r}")
    finally:
        conn.close()

    res["success"] = True
    res["db"] = str(db_path)
    sys.stdout.write(json.dumps(res, ensure_ascii=False) + "\n")
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
