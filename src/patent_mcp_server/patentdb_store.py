"""patentdb_store.py — patentdb 結構化書目層（unified database）

雙層 patentdb 的「結構化層」：sqlite 存全域書目事實 + FTS5 全文。
與既有 blob 層（<國別>/<正規化號>/{specification.pdf/xml, figures/}）並存。

設計哲學（見 plans/patentdb_unified-database/design.md）：
- 被動累加：所有書目欄位 nullable，register 不要求完整，upsert 漸進合併不覆寫。
- 成本加權收集：acquisition_cost 粗分 high/low/free，貴的取得一次絕不重抓。
- 只管書目：無 screening 評分表（評分是 by-project 產物，留專案 CSV）。
- 百萬級：pubno PK + 二級索引 + FTS5 external-content + WAL + 批次 transaction。
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = __import__("logging").getLogger(__name__)

# ---- DB 路徑解析（複用 patents.py 的 _get_db_root 邏輯，避免循環 import 故獨立一份）----

def _resolve_db_root() -> Path:
    import os
    env_root = os.environ.get("PATENTS_DB_ROOT")
    if env_root:
        return Path(env_root)
    curr = Path(__file__).resolve()
    for _ in range(10):
        if (curr / ".mcp.json").is_file():
            return curr / "patentdb"
        curr = curr.parent
    return Path(__file__).resolve().parent.parent.parent / "patentdb"


def _db_path() -> Path:
    root = _resolve_db_root()
    root.mkdir(parents=True, exist_ok=True)
    return root / "patentdb.sqlite"


# ---- pubno 正規化（與 patents.py _get_patent_country_and_normalized_no 對齊）----

def normalize_pubno(publication_number: str) -> Tuple[str, str]:
    import re
    # strip whitespace, slashes, hyphens, commas, dots (format separators)
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
    """正規化後的 canonical key（country + normalized_no），用作 patents.pubno PK。"""
    country, norm = normalize_pubno(publication_number)
    return f"{country}{norm}"


# ---- schema ----

_TEXT_COLS = [
    "country", "normalized_no", "kind", "title_orig", "title_en", "abstract",
    "claim1", "applicants", "inventors", "application_no", "application_date",
    "publication_date", "priority_date", "cpc_codes", "ipc_codes", "family_id",
    "pdf_path", "pdf_sha256", "xml_path", "xml_sha256", "figures_json",
    "first_source", "acquisition_cost", "created_at", "updated_at",
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS patents (
  pubno            TEXT PRIMARY KEY,
  country          TEXT NOT NULL,
  normalized_no    TEXT NOT NULL,
  kind             TEXT,
  title_orig       TEXT,
  title_en         TEXT,
  abstract         TEXT,
  claim1           TEXT,
  applicants       TEXT,
  inventors        TEXT,
  application_no   TEXT,
  application_date TEXT,
  publication_date TEXT,
  priority_date    TEXT,
  cpc_codes        TEXT,
  ipc_codes        TEXT,
  family_id        TEXT,
  pdf_path         TEXT,
  pdf_sha256       TEXT,
  xml_path         TEXT,
  xml_sha256       TEXT,
  figures_json     TEXT,
  first_source     TEXT,
  acquisition_cost TEXT,
  scraping_used    INTEGER DEFAULT 0,
  created_at       TEXT,
  updated_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_patents_country  ON patents(country);
CREATE INDEX IF NOT EXISTS idx_patents_family   ON patents(family_id);
CREATE INDEX IF NOT EXISTS idx_patents_appdate  ON patents(application_date);
CREATE INDEX IF NOT EXISTS idx_patents_acq_cost ON patents(acquisition_cost);

-- trigram tokenizer：支援 CJK 子字串匹配（unicode61 不切中文詞）
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


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    return conn


# 完整度判斷：哪些欄位/blob 有實際內容
_COMPLETENESS_FIELDS = ["title_orig", "abstract", "claim1", "cpc_codes", "family_id"]
_COMPLETENESS_BLOBS = ["pdf_path", "xml_path", "figures_json"]


def _completeness(row: Dict[str, Any]) -> Dict[str, bool]:
    flags = {}
    for f in _COMPLETENESS_FIELDS + _COMPLETENESS_BLOBS:
        v = row.get(f)
        flags[f] = bool(v and str(v).strip() and v not in ("[]", "{}"))
    # title 任一語系有值即算有標題
    flags["title"] = bool(
        (row.get("title_orig") and str(row.get("title_orig")).strip())
        or (row.get("title_en") and str(row.get("title_en")).strip())
    )
    return flags


# ---- put：漸進合併 upsert（DD-3/4）----

def put(
    publication_number: str,
    fields: Optional[Dict[str, Any]] = None,
    blobs: Optional[Dict[str, Any]] = None,
    acquisition_cost: Optional[str] = None,
    overwrite: bool = False,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """Upsert 一件專利書目，漸進合併（COALESCE 既有非空，只填補 NULL，除非 overwrite）。

    fields: 書目欄位 map（全可選，子集即可）。
    blobs:  {pdf:{path,sha256}, xml:{path,sha256}, figures:[{name,path,sha256}]}。
    acquisition_cost: high/low/free（粗分級，DD-9）。
    """
    own = conn is None
    if own:
        conn = _connect()
    try:
        pubno = canonical_pubno(publication_number)
        country, norm = normalize_pubno(publication_number)
        now = time.strftime("%Y-%m-%dT%H:%M:%S+08:00")

        incoming: Dict[str, Any] = {}
        fields = fields or {}
        for k in _TEXT_COLS:
            if k in fields and fields[k] not in (None, ""):
                incoming[k] = _maybe_json(fields[k])
        # blobs
        blobs = blobs or {}
        if "pdf" in blobs and isinstance(blobs["pdf"], dict):
            incoming["pdf_path"] = blobs["pdf"].get("path")
            incoming["pdf_sha256"] = blobs["pdf"].get("sha256")
        if "xml" in blobs and isinstance(blobs["xml"], dict):
            incoming["xml_path"] = blobs["xml"].get("path")
            incoming["xml_sha256"] = blobs["xml"].get("sha256")
        if "figures" in blobs and blobs["figures"]:
            incoming["figures_json"] = json.dumps(blobs["figures"], ensure_ascii=False)
        if acquisition_cost:
            incoming["acquisition_cost"] = acquisition_cost
        incoming["country"] = country
        incoming["normalized_no"] = norm

        existing = conn.execute("SELECT * FROM patents WHERE pubno=?", (pubno,)).fetchone()
        if existing is None:
            cols = ["pubno", "created_at", "updated_at"] + list(incoming.keys())
            vals = [pubno, now, now] + list(incoming.values())
            placeholders = ",".join("?" * len(cols))
            conn.execute(
                f"INSERT INTO patents ({','.join(cols)}) VALUES ({placeholders})", vals
            )
            conn.commit()
            row = dict(conn.execute("SELECT * FROM patents WHERE pubno=?", (pubno,)).fetchone())
            return {"pubno": pubno, "action": "created", "completeness": _completeness(row)}

        # 漸進合併
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
            conn.execute(
                f"UPDATE patents SET {set_clause} WHERE pubno=?",
                list(updates.values()) + [pubno],
            )
            conn.commit()
        row = dict(conn.execute("SELECT * FROM patents WHERE pubno=?", (pubno,)).fetchone())
        return {
            "pubno": pubno,
            "action": "updated" if updates else "unchanged",
            "merged_fields": [k for k in updates if k != "updated_at"],
            "completeness": _completeness(row),
        }
    finally:
        if own:
            conn.close()


def _maybe_json(v: Any) -> Any:
    """list/dict 欄位（applicants/inventors/cpc_codes/ipc_codes）存成 JSON 字串。"""
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return v


# ---- query：pubno 精查 / FTS / country 過濾（DD-12 腳踏兩條船庫側入口）----

def query(
    publication_number: Optional[str] = None,
    fts: Optional[str] = None,
    country: Optional[str] = None,
    limit: int = 20,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    own = conn is None
    if own:
        conn = _connect()
    try:
        if publication_number:
            pubno = canonical_pubno(publication_number)
            r = conn.execute("SELECT * FROM patents WHERE pubno=?", (pubno,)).fetchone()
            if r is None:
                return {"found": False, "pubno": pubno}
            row = dict(r)
            return {"found": True, "patent": _public_row(row), "completeness": _completeness(row)}

        if fts:
            # trigram tokenizer 需 ≥3 字元；2 字 CJK 詞（装修/监理）走 LIKE fallback
            term = fts.strip()
            if len(term) >= 3:
                rows = conn.execute(
                    """SELECT p.*, bm25(patents_fts) AS rank
                       FROM patents_fts JOIN patents p ON p.rowid = patents_fts.rowid
                       WHERE patents_fts MATCH ? ORDER BY rank LIMIT ?""",
                    (term, limit),
                ).fetchall()
                mode = "fts5"
            else:
                like = f"%{term}%"
                rows = conn.execute(
                    """SELECT *, 0 AS rank FROM patents
                       WHERE title_orig LIKE ? OR title_en LIKE ? OR abstract LIKE ? OR claim1 LIKE ?
                       ORDER BY updated_at DESC LIMIT ?""",
                    (like, like, like, like, limit),
                ).fetchall()
                mode = "like_short"
            return {
                "count": len(rows),
                "match_mode": mode,
                "results": [
                    {**_public_row(dict(r)), "rank": r["rank"], "completeness": _completeness(dict(r))}
                    for r in rows
                ],
            }

        if country:
            rows = conn.execute(
                "SELECT * FROM patents WHERE country=? ORDER BY updated_at DESC LIMIT ?",
                (country.upper(), limit),
            ).fetchall()
            return {"count": len(rows), "results": [_public_row(dict(r)) for r in rows]}

        # no filter → recent
        rows = conn.execute(
            "SELECT * FROM patents ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) c FROM patents").fetchone()["c"]
        return {"count": len(rows), "total": total, "results": [_public_row(dict(r)) for r in rows]}
    finally:
        if own:
            conn.close()


_JSON_COLS = {"applicants", "inventors", "cpc_codes", "ipc_codes", "figures_json"}


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


# ---- import_csv：只匯入書目（DD-2），批次 transaction（DD-10）----

# candidates.csv 中文表頭 → patents 欄位映射（對齊 screening_table.py COLUMNS）
_CSV_HEADER_MAP = {
    "專利號": "pubno",
    "名稱": "title_orig",
    "標題": "title_orig",
    "摘要": "abstract",
    "獨立項": "claim1",
    "Claim1": "claim1",
    "申請號": "application_no",
    "家族": "family_id",
    "優先權日": "priority_date",
    "優先權": "priority_date",
    "申請日": "application_date",
    "公開/公告日": "publication_date",
    "CPC": "cpc_codes",
    "推測CPC": "cpc_codes",
    "IPC": "ipc_codes",
    "申請人": "applicants",
}
# 評分欄位（DD-2 不入庫，僅辨識以跳過）
_SCREENING_HEADERS = {"相關性", "分數", "技術要點", "命中要件", "命中/落差要件", "理由", "人工複核", "_hscore", "_feats", "_domain", "類別"}


def import_csv(csv_path: str, conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """從 candidates.csv 批次匯入書目（只書目，不碰評分 DD-2）。"""
    import csv as _csv

    own = conn is None
    if own:
        conn = _connect()
    try:
        created = updated = skipped = 0
        path = Path(csv_path)
        if not path.is_file():
            return {"error": "csv_not_found", "path": str(path)}
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = _csv.DictReader(fh)
            headers = reader.fieldnames or []
            # 建欄位映射（只取書目欄，跳過評分欄）
            col_for = {}
            for h in headers:
                hs = (h or "").strip()
                if hs in _CSV_HEADER_MAP:
                    col_for[h] = _CSV_HEADER_MAP[hs]
            conn.execute("BEGIN")
            for rec in reader:
                pub_raw = (rec.get("專利號") or rec.get("pubno") or "").strip()
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
                res = put(pub_raw, fields=fields, acquisition_cost="low", conn=conn)
                if res["action"] == "created":
                    created += 1
                elif res["action"] == "updated":
                    updated += 1
                else:
                    skipped += 1
            conn.commit()
        return {"imported": created, "updated": updated, "skipped": skipped, "csv": str(path)}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return {"error": "import_failed", "detail": str(e), "csv": str(csv_path)}
    finally:
        if own:
            conn.close()


# gpss_to_records / google_to_records 的 record dict 欄位 → patents 欄位
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


def import_records(
    records: List[Dict[str, Any]],
    acquisition_cost: str = "low",
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """Inline-absorb search-tool record dicts (gpss_to_records / google_to_records)
    into patentdb — bibliographic only (DD-2), single transaction (DD-10, DD-11).

    Called as a side-effect when build_screening_table lands a CSV: the records are
    already in memory, so absorption costs zero extra toolcall and zero network.
    """
    own = conn is None
    if own:
        conn = _connect()
    try:
        created = updated = skipped = 0
        conn.execute("BEGIN")
        for rec in records or []:
            pub_raw = (rec.get("pubno") or "").strip()
            if not pub_raw:
                skipped += 1
                continue
            fields: Dict[str, Any] = {}
            for rk, col in _RECORD_FIELD_MAP.items():
                v = rec.get(rk)
                if v not in (None, "", []):
                    fields[col] = v
            res = put(pub_raw, fields=fields, acquisition_cost=acquisition_cost, conn=conn)
            if res["action"] == "created":
                created += 1
            elif res["action"] == "updated":
                updated += 1
            else:
                skipped += 1
        conn.commit()
        return {"imported": created, "updated": updated, "skipped": skipped}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return {"error": "import_records_failed", "detail": str(e)}
    finally:
        if own:
            conn.close()


def stats(conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    own = conn is None
    if own:
        conn = _connect()
    try:
        total = conn.execute("SELECT COUNT(*) c FROM patents").fetchone()["c"]
        by_country = {
            r["country"]: r["c"]
            for r in conn.execute("SELECT country, COUNT(*) c FROM patents GROUP BY country").fetchall()
        }
        with_claim1 = conn.execute(
            "SELECT COUNT(*) c FROM patents WHERE claim1 IS NOT NULL AND claim1 != ''"
        ).fetchone()["c"]
        return {"total": total, "by_country": by_country, "with_claim1": with_claim1, "db_path": str(_db_path())}
    finally:
        if own:
            conn.close()
