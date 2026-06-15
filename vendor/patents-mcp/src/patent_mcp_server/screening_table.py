"""Screening-table assembly: normalize search hits → dedup by family → select
columns by purpose → write a human-readable CSV.

Columns are selectable (欄位隨選制): a mandatory CORE is always kept, a PURPOSE
preset adds groups (classification for landscape, dates for prior-art/FTO, etc.),
and AI writeback columns are always appended for the agent to fill during the
digestion pass. Unavailable fields are emitted empty (honestly blank), never faked.
"""
from __future__ import annotations

import csv
import html as _html
import io
from typing import Any, Dict, List, Optional

# ── column dictionary ───────────────────────────────────────────────
# key -> (header, kind). kind: "core" | "select" | "ai" | "derived"
COLUMNS: Dict[str, str] = {
    # core (mandatory)
    "pubno": "專利號",
    "appno": "申請號",
    "title": "名稱",
    "abstract": "摘要",
    "claim1": "獨立項",
    "family": "家族",          # derived: family_id (+N members)
    # selectable
    "cpc": "CPC",
    "ipc": "IPC",
    "uspc": "USPC",
    "prio_date": "優先權日",
    "app_date": "申請日",
    "pub_date": "公開/公告日",
    "grant_date": "核准日",
    "assignee": "申請人",
    "inventor": "發明人",
    "legal_status": "法律狀態",
    "citations": "引用",
    # AI writeback (always appended)
    "relevance": "相關性",
    "score": "分數",
    "tech_gist": "技術要點",
    "feat": "命中/落差要件",
    "reason": "理由",
}

CORE_KEYS = ["pubno", "appno", "title", "abstract", "claim1", "family"]
AI_KEYS = ["relevance", "score", "tech_gist", "feat", "reason"]

PRESETS: Dict[str, List[str]] = {
    "minimal": [],
    "landscape": ["cpc", "ipc", "assignee"],
    "priorart": ["prio_date", "app_date", "pub_date", "cpc"],
    "fto": ["app_date", "grant_date", "assignee", "legal_status"],
}


def resolve_columns(
    purpose: str = "landscape",
    extra: Optional[List[str]] = None,
    exclude: Optional[List[str]] = None,
) -> List[str]:
    """core ∪ preset(purpose) ∪ extra − exclude, then AI columns appended.
    Core and AI columns cannot be excluded."""
    exclude = set(exclude or [])
    ordered = list(CORE_KEYS) + PRESETS.get(purpose, PRESETS["landscape"]) + list(extra or [])
    seen, cols = set(), []
    for k in ordered:
        if k in COLUMNS and k not in seen and k not in CORE_KEYS:
            # selectable: honor exclude
            if k in exclude:
                continue
        if k in COLUMNS and k not in seen:
            seen.add(k)
            cols.append(k)
    # AI columns always last, never excluded
    for k in AI_KEYS:
        if k not in seen:
            cols.append(k)
            seen.add(k)
    return cols


def dedup_by_family(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse INPADOC family members to one representative row; the rep's
    `members` lists the collapsed publication numbers. Records without a
    family_id pass through unchanged. No-op when no family_id is present
    (e.g. source lacks family data)."""
    by_family: Dict[str, Dict[str, Any]] = {}
    out: List[Dict[str, Any]] = []
    for r in records:
        fam = (r.get("family_id") or "").strip()
        r.setdefault("members", [])
        if fam:
            if fam in by_family:
                by_family[fam]["members"].append(r.get("pubno", ""))
                continue
            by_family[fam] = r
        out.append(r)
    return out


def _render(rec: Dict[str, Any], key: str) -> str:
    if key == "family":
        fam = rec.get("family_id") or ""
        n = len(rec.get("members") or [])
        if fam and n:
            return f"{fam} (+{n})"
        return fam
    if key in AI_KEYS:
        return ""  # filled by the agent later
    val = rec.get(key, "")
    if isinstance(val, list):
        return "; ".join(str(x) for x in val)
    return "" if val is None else str(val)


def build_csv(records: List[Dict[str, Any]], columns: List[str]) -> bytes:
    """Render records into a UTF-8 CSV (bytes) with the given column keys."""
    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    writer.writerow([COLUMNS[k] for k in columns])
    for rec in records:
        writer.writerow([_render(rec, k) for k in columns])
    return buf.getvalue().encode("utf-8")


# ── source adapters: normalize a source's hits into common record dicts ──

def google_to_records(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """gpatents_search results → records. Google search gives no appno/claim1/
    cpc/ipc/family_id; those land empty (fill via GPSS or gpatents_get)."""
    recs = []
    for x in results:
        recs.append({
            "pubno": x.get("publication_number", ""),
            "appno": "",
            "title": x.get("title", ""),
            "abstract": _html.unescape(x.get("snippet", "") or ""),  # snippet only
            "claim1": "",
            "family_id": "",   # Google search exposes country_status, not a family id
            "prio_date": x.get("priority_date", ""),
            "app_date": x.get("filing_date", ""),
            "pub_date": x.get("publication_date", ""),
            "grant_date": x.get("grant_date", ""),
            "assignee": x.get("assignee", ""),
            "inventor": x.get("inventor", ""),
        })
    return recs


def gpss_to_records(gpss_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    """GPSS search JSON → records. GPSS gives PN/AN/TI/AB/CL/IC/CS/UC/PR/AD/ID/
    PA/IN in one call. Field paths are best-effort per the API doc and must be
    verified against a live userCode response."""
    api = gpss_json.get("data", {}).get("gpss-API", gpss_json.get("gpss-API", {}))
    rows = api.get("patents") or api.get("results") or api.get("record") or []
    if isinstance(rows, dict):
        rows = [rows]
    recs = []
    for r in rows:
        claims = r.get("CL") or r.get("claims") or ""
        claim1 = ""
        if isinstance(claims, list):
            claim1 = str(claims[0]) if claims else ""
        elif isinstance(claims, str):
            # first claim ≈ up to the second numbered marker; keep it simple.
            claim1 = claims.strip().split("\n2.")[0][:2000]
        recs.append({
            "pubno": r.get("PN", ""),
            "appno": r.get("AN", ""),
            "title": r.get("TI", ""),
            "abstract": r.get("AB", ""),
            "claim1": claim1,
            "family_id": r.get("family_id", ""),  # verify GPSS exposes this
            "cpc": r.get("CS", ""),
            "ipc": r.get("IC", ""),
            "uspc": r.get("UC", ""),
            "prio_date": r.get("PR", ""),
            "app_date": r.get("AD", ""),
            "pub_date": r.get("ID", ""),
            "assignee": r.get("PA", ""),
            "inventor": r.get("IN", ""),
        })
    return recs


# Fields that no current source fills in-band — surfaced honestly as gaps.
KNOWN_GAPS = {
    "legal_status": "需 EPO/USPTO 法律狀態查詢(FTO 用)",
    "citations": "需 EPO/GPSS 引用資料",
    "family": "Google 路無 family_id;去重需 GPSS/EPO 確認",
}
