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


def _g(node: Any, *keys: str, default: str = "") -> Any:
    """Safe nested get over GPSS dicts."""
    cur = node
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if cur is not None else default


def _as_list(x: Any) -> List[Any]:
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def gpss_to_records(gpss_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    """GPSS search JSON → records. Robust type handling for nested data structures."""
    api = gpss_json.get("data", {}).get("gpss-API") or gpss_json.get("gpss-API", {})
    rows = _as_list(_g(api, "patent", "patentcontent"))
    recs = []
    for r in rows:
        # claims[0] -> Claim1
        claims = _as_list(_g(r, "claims", "claim"))
        claim1 = ""
        if claims:
            first_claim = claims[0]
            if isinstance(first_claim, dict):
                ct = first_claim.get("claim-text", "")
                claim1 = " ".join(ct) if isinstance(ct, list) else str(ct or "")
            else:
                claim1 = str(first_claim)
        abstract = _g(r, "abstract", "p")
        if isinstance(abstract, list):
            abstract = " ".join(str(x) for x in abstract)
        
        # Safe applicant parse
        applicants_list = _as_list(_g(r, "parties", "applicants", "applicant"))
        applicant_names = []
        for a in applicants_list:
            if isinstance(a, dict):
                name = a.get("english-name") or a.get("name") or ""
                if name: applicant_names.append(name)
            else:
                applicant_names.append(str(a))
        applicants = "; ".join(applicant_names)
        
        # Safe inventor parse
        inventors_list = _as_list(_g(r, "parties", "inventors", "inventor"))
        inventor_names = []
        for i in inventors_list:
            if isinstance(i, dict):
                name = i.get("english-name") or i.get("name") or ""
                if name: inventor_names.append(name)
            else:
                inventor_names.append(str(i))
        inventors = "; ".join(inventor_names)
        
        # Safe CPC/IPC parse
        cpc = "; ".join(
            (c.get("keyValue", "") if isinstance(c, dict) else str(c))
            for c in _as_list(_g(r, "classifications-cpc", "cpc"))[:6]
        )
        ipc = "; ".join(
            (c.get("keyValue", "") if isinstance(c, dict) else str(c))
            for c in _as_list(_g(r, "classifications-ipc", "ipc"))[:6]
        )
        
        # Safe Priority claim parse
        prio = _as_list(_g(r, "priority-claims", "priority-claim"))
        prio_date = ""
        if prio:
            first_prio = prio[0]
            if isinstance(first_prio, dict):
                prio_date = first_prio.get("date", "")
            else:
                prio_date = str(first_prio)
                
        recs.append({
            "pubno": _g(r, "publication-reference", "doc-number"),
            "appno": _g(r, "application-reference", "doc-number"),
            "title": _g(r, "patent-title", "english-title") or _g(r, "patent-title", "chinese-title"),
            "abstract": str(abstract or ""),
            "claim1": claim1,
            "family_id": "",  # GPSS doesn't expose INPADOC family; use epo_family
            "cpc": cpc,
            "ipc": ipc,
            "prio_date": prio_date,
            "app_date": _g(r, "application-reference", "date"),
            "pub_date": _g(r, "publication-reference", "date"),
            "assignee": applicants,
            "inventor": inventors,
        })
    return recs


# Fields that no current source fills in-band — surfaced honestly as gaps.
KNOWN_GAPS = {
    "legal_status": "需 EPO/USPTO 法律狀態查詢(FTO 用)",
    "citations": "需 EPO/GPSS 引用資料",
    "family": "Google 路無 family_id;去重需 GPSS/EPO 確認",
}
