"""Source-ladder search dispatcher (plans/patentmcp_search-dispatcher).

Single entry point for patent SEARCH. The ladder — GPSS (TIPO official) →
EPO OPS → USPTO PPUBS → (gated) Google Patents scraping — is decided HERE,
server-side, from configured() + query-axis capability (DD-3). The AI never
picks a source; the scraping tail requires an explicit allow_scraping=True
(DD-2, same gate pattern as fetch_patent_pdf). Every level's attempt lands in
`provenance` (DD-5); an all-official miss fails fast with SCRAPING_REQUIRED /
ALL_SOURCES_MISS — never a silent fallback.

Clients are injected by the caller (patents.py module singletons) so tests can
monkeypatch them; this module never touches the client layer.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from patent_mcp_server import screening_table as _st

logger = logging.getLogger(__name__)

# ── capability matrix (DD-3; data-schema.json AXIS_CAPABILITY) ──────
# Hard search axes decide routing. date/databases are soft filters:
# they never disqualify a level (except PPUBS is US-only, and gpatents maps
# databases → country prefixes).
AXIS_CAPABILITY: Dict[str, Set[str]] = {
    "gpss": {"cpc", "ipc", "keyword", "applicant", "inventor_country",
             "pub_number", "date", "databases"},
    "epo": {"cpc", "ipc", "keyword", "applicant", "pub_number", "date"},
    "ppubs": {"uspc", "cpc", "ipc", "keyword", "applicant", "date"},
    "gpatents": {"keyword", "pub_number", "date", "databases"},
}

_HARD_AXES = ("cpc", "ipc", "uspc", "keyword", "applicant",
              "inventor_country", "pub_number")

# EPO search only returns publication numbers; biblio is a second stage under
# the OPS 15/min throttle (DD-4). Cap the per-call biblio fan-out.
EPO_BIBLIO_MAX = 15

# Honest per-source gaps (DD-5): fields the source cannot fill in-band.
SOURCE_GAPS: Dict[str, List[str]] = {
    "gpss": [
        "family_id: GPSS 不提供 INPADOC family_id,家族去重需 epo_family",
        "legal_status: 需 EPO/USPTO 法律狀態查詢",
        "citations: 需 EPO/GPSS 引用資料",
    ],
    "epo": [
        "claim1: EPO biblio 二段不含 claims,需 patent_get_claim1 補抓",
        "appno/dates: biblio 路徑不含申請號與日期欄位",
        "cpc: EPO biblio 路徑僅回 IPC",
        "family_id: 需 epo_family 另查",
        "inventor: biblio 路徑未解析發明人",
    ],
    "ppubs": [
        "claim1: PPUBS 檢索命中不含 claims,需 ppubs_batch_get_claims 補抓",
        "abstract: 檢索命中僅部分含摘要",
        "family_id: 需 epo_family 另查",
    ],
    "gpatents": [
        "appno/claim1/cpc/ipc: Google 檢索頁不提供,需 gpatents_get 補抓",
        "family_id: 需 epo_family 另查",
        "abstract: 僅 snippet 摘錄,非完整摘要",
    ],
}


class BackendError(Exception):
    """Single-level backend failure — recorded in provenance, ladder continues."""


@dataclass
class QuerySpec:
    """Normalized patent_search parameters (data-schema.json QuerySpec)."""
    cpc: Optional[str] = None
    ipc: Optional[str] = None
    uspc: Optional[str] = None
    keyword: Optional[str] = None
    keyword_field: str = "TI/AB"
    applicant: Optional[str] = None
    inventor_country: Optional[str] = None
    pub_number: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    databases: Optional[List[str]] = None
    num: int = 30
    skip: int = 0
    allow_scraping: bool = False

    def hard_axes(self) -> Set[str]:
        return {a for a in _HARD_AXES if getattr(self, a)}


def normalize_query(**kwargs: Any) -> QuerySpec:
    """Strip strings, clamp pagination, default keyword_field."""
    clean: Dict[str, Any] = {}
    for k, v in kwargs.items():
        if isinstance(v, str):
            v = v.strip() or None
        clean[k] = v
    spec = QuerySpec(**clean)
    spec.keyword_field = spec.keyword_field or "TI/AB"
    spec.num = max(1, int(spec.num or 30))
    spec.skip = max(0, int(spec.skip or 0))
    spec.allow_scraping = bool(spec.allow_scraping)
    if spec.databases:
        spec.databases = [str(d).strip() for d in spec.databases if str(d).strip()]
        spec.databases = spec.databases or None
    return spec


# ── provenance helpers ──────────────────────────────────────────────

def _entry(source: str, status: str, reason: Optional[str] = None,
           scraping: bool = False, elapsed_ms: Optional[int] = None) -> Dict[str, Any]:
    return {"source": source, "status": status, "reason": reason,
            "scraping": scraping, "elapsed_ms": elapsed_ms}


def _error_reason(exc: Exception) -> str:
    msg = str(exc)
    m = re.search(r"\b([45]\d\d)\b", msg)
    if m:
        return f"http_error:{m.group(1)}"
    return msg[:160] or exc.__class__.__name__


def _to_int(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ── per-level runners (each returns (records, total, note)) ─────────

async def _run_gpss(spec: QuerySpec, gpss_client: Any) -> Tuple[List[Dict[str, Any]], Optional[int], Optional[str]]:
    # local import keeps the module import-light; GPSSCondition is a pure value
    from patent_mcp_server.gpss.client import GPSSCondition

    conditions: List[Any] = []
    if spec.cpc:
        conditions.append(GPSSCondition("CS", spec.cpc))
    if spec.ipc:
        conditions.append(GPSSCondition("IC", spec.ipc))
    if spec.keyword:
        conditions.append(GPSSCondition(spec.keyword_field or "TI/AB", spec.keyword))
    if spec.inventor_country:
        conditions.append(GPSSCondition("IY", spec.inventor_country))
    if spec.applicant:
        conditions.append(GPSSCondition("AX", spec.applicant))
    if spec.pub_number:
        conditions.append(GPSSCondition("PN", spec.pub_number))
    if spec.date_from or spec.date_to:
        conditions.append(GPSSCondition("ID", f"{spec.date_from or ''}:{spec.date_to or ''}"))

    target = spec.num
    chunk = 50
    records: List[Dict[str, Any]] = []
    skip = spec.skip
    total: Optional[int] = None
    while len(records) < target:
        cur = min(chunk, target - len(records))
        res = await gpss_client.search(
            conditions=conditions, databases=spec.databases,
            fields="PN,AN,ID,AD,PR,TI,AB,CL,IC,CS,UC,PA,IN",
            num=cur, skip=skip, fmt="json",
        )
        if not res.get("success"):
            if records:
                logger.warning("GPSS pagination failed at skip=%d: %s",
                               skip, res.get("error") or res.get("message"))
                break
            # status=success + message == "no record found" boilerplate → zero hits
            if res.get("status") == "success":
                return [], _to_int(res.get("total")) or 0, None
            raise BackendError(str(res.get("error") or res.get("message") or "GPSS search failed"))
        page = _st.gpss_to_records(res)
        total = _to_int(res.get("total"))
        if not page:
            break
        records.extend(page)
        if total is not None and skip + len(records) >= total:
            break
        skip += len(page)
        await asyncio.sleep(1.0)
    return records[:target], total, None


async def _run_epo(spec: QuerySpec, epo_client: Any) -> Tuple[List[Dict[str, Any]], Optional[int], Optional[str]]:
    parts: List[str] = []
    if spec.cpc:
        parts.append(f"cpc={spec.cpc}")
    if spec.ipc:
        parts.append(f"ic={spec.ipc}")
    if spec.keyword:
        kw = spec.keyword
        parts.append(f'txt="{kw}"' if " " in kw else f"txt={kw}")
    if spec.applicant:
        pa = spec.applicant
        parts.append(f'pa="{pa}"' if " " in pa else f"pa={pa}")
    if spec.pub_number:
        parts.append(f"pn={spec.pub_number}")
    if spec.date_from and spec.date_to:
        parts.append(f'pd within "{spec.date_from} {spec.date_to}"')
    elif spec.date_from:
        parts.append(f"pd >= {spec.date_from}")
    elif spec.date_to:
        parts.append(f"pd <= {spec.date_to}")
    cql = " and ".join(parts)

    n = min(spec.num, 100)
    res = await epo_client.search(cql, range_=f"{spec.skip + 1}-{spec.skip + n}")
    if not res.get("success"):
        raise BackendError(str(res.get("error") or "EPO search failed"))
    pubs = res.get("results") or []
    total = _to_int(res.get("total"))
    if not pubs:
        return [], total, None

    note = "biblio_truncated" if len(pubs) > EPO_BIBLIO_MAX else None
    records: List[Dict[str, Any]] = []
    for pub in pubs[:EPO_BIBLIO_MAX]:
        try:
            b = await epo_client.biblio(pub)
        except Exception as e:  # noqa: BLE001 — one biblio miss must not kill the level
            logger.warning("EPO biblio failed for %s: %s", pub, e)
            b = {}
        records.append(_st.epo_biblio_to_record(pub, b if b.get("success") else {}))
    return records, total, note


async def _run_ppubs(spec: QuerySpec, ppubs_client: Any) -> Tuple[List[Dict[str, Any]], Optional[int], Optional[str]]:
    parts: List[str] = []
    if spec.uspc:
        uspc = spec.uspc
        parts.append(uspc if uspc.upper().startswith("CCL/") else f"CCL/{uspc}")
    if spec.cpc:
        parts.append(f"CPC/{spec.cpc}")
    if spec.ipc:
        parts.append(f"IPC/{spec.ipc}")
    if spec.keyword:
        parts.append(f'"{spec.keyword}"')
    if spec.applicant:
        parts.append(f'"{spec.applicant}".as.')
    query = " AND ".join(parts)
    if spec.date_from and spec.date_to:
        query += f' AND @pd>="{spec.date_from}"<="{spec.date_to}"'
    elif spec.date_from:
        query += f' AND @pd>="{spec.date_from}"'
    elif spec.date_to:
        query += f' AND @pd<="{spec.date_to}"'

    res = await ppubs_client.run_query(
        query=query, sources=["USPAT", "US-PGPUB"],
        start=spec.skip, limit=spec.num,
    )
    if not isinstance(res, dict):
        raise BackendError("PPUBS returned a non-dict response")
    if res.get("error"):
        raise BackendError(str(res.get("message") or res.get("errorCode") or "PPUBS query failed"))
    records = _st.ppubs_to_records(res)
    total = _to_int(res.get("totalResults") or res.get("numFound")
                    or res.get("recordTotalQuantity"))
    return records[:spec.num], total, None


async def _run_gpatents(spec: QuerySpec, gpatents_client: Any) -> Tuple[List[Dict[str, Any]], Optional[int], Optional[str]]:
    q = spec.keyword or spec.pub_number or ""
    countries = None
    if spec.databases:
        countries = sorted({d[:2].upper() for d in spec.databases if len(d) >= 2})
    res = await gpatents_client.search(
        query=q,
        countries=countries,
        num=min(spec.num, 100),
        page=0,
        before=(f"publication:{spec.date_to}" if spec.date_to else None),
        after=(f"publication:{spec.date_from}" if spec.date_from else None),
        status=None,
        type_=None,
    )
    if not res.get("success"):
        raise BackendError(str(res.get("error") or "Google Patents search failed"))
    records = _st.google_to_records(res.get("results") or [])
    total = _to_int(res.get("total_num_results"))
    return records, total, None


# ── the ladder ──────────────────────────────────────────────────────

def _envelope(success: bool, records: List[Dict[str, Any]], source: Optional[str],
              provenance: List[Dict[str, Any]], gaps: List[str],
              total: Optional[int], error_code: Optional[str] = None,
              message: Optional[str] = None) -> Dict[str, Any]:
    env: Dict[str, Any] = {
        "success": success, "records": records, "source": source,
        "provenance": provenance, "gaps": gaps, "total": total,
    }
    if error_code:
        env["error_code"] = error_code
    if message:
        env["message"] = message
    return env


async def dispatch_search(
    spec: QuerySpec,
    *,
    gpss_client: Any,
    epo_client: Any,
    ppubs_client: Any,
    gpatents_client: Any,
) -> Dict[str, Any]:
    """Run the source ladder for a normalized QuerySpec.

    Returns a PatentSearchEnvelope (data-schema.json): {success, records[],
    source, provenance[], gaps[], total, error_code?}.
    """
    axes = spec.hard_axes()
    if not axes:
        # fail fast, no backend touched (errors.md INVALID_PARAMS)
        return _envelope(
            False, [], None, [], [], None, error_code="INVALID_PARAMS",
            message="至少需要一個檢索軸 (cpc/ipc/uspc/keyword/applicant/pub_number)",
        )

    provenance: List[Dict[str, Any]] = []
    hit: Optional[Tuple[str, List[Dict[str, Any]], Optional[int]]] = None

    officials = (
        ("gpss", _run_gpss, gpss_client),
        ("epo", _run_epo, epo_client),
        ("ppubs", _run_ppubs, ppubs_client),
    )
    for name, runner, client in officials:
        if hit is not None:
            provenance.append(_entry(name, "skipped", "earlier_source_hit"))
            continue
        if axes - AXIS_CAPABILITY[name]:
            provenance.append(_entry(name, "skipped", "axis_unsupported"))
            continue
        if name in ("gpss", "epo") and not client.configured():
            provenance.append(_entry(name, "skipped", "not_configured"))
            continue
        if name == "ppubs" and spec.databases and not any(
                str(d).upper().startswith("US") for d in spec.databases):
            provenance.append(_entry(name, "skipped", "us_only_source"))
            continue
        t0 = time.monotonic()
        try:
            records, total, note = await runner(spec, client)
        except Exception as e:  # noqa: BLE001 — DD: record + continue, never raise
            provenance.append(_entry(name, "error", _error_reason(e),
                                     elapsed_ms=int((time.monotonic() - t0) * 1000)))
            logger.warning("patent_search level %s errored: %s", name, e)
            continue
        elapsed = int((time.monotonic() - t0) * 1000)
        if records:
            provenance.append(_entry(name, "hit", note, elapsed_ms=elapsed))
            hit = (name, records, total)
        else:
            provenance.append(_entry(name, "miss", "zero_hits", elapsed_ms=elapsed))

    if hit is None:
        # ── gated gpatents tail (DD-2) ──
        if not spec.allow_scraping:
            provenance.append(_entry("gpatents", "skipped",
                                     "scraping_not_authorized", scraping=True))
            return _envelope(
                False, [], None, provenance, [], None,
                error_code="SCRAPING_REQUIRED",
                message=("官方來源 (GPSS/EPO/PPUBS) 全數未命中;Google Patents 為爬蟲來源,"
                         "需取得使用者明確授權後帶 allow_scraping=True 重呼叫"),
            )
        if axes - AXIS_CAPABILITY["gpatents"]:
            provenance.append(_entry("gpatents", "skipped", "axis_unsupported",
                                     scraping=True))
        else:
            t0 = time.monotonic()
            try:
                records, total, note = await _run_gpatents(spec, gpatents_client)
                elapsed = int((time.monotonic() - t0) * 1000)
                if records:
                    provenance.append(_entry("gpatents", "hit", note,
                                             scraping=True, elapsed_ms=elapsed))
                    hit = ("gpatents", records, total)
                else:
                    provenance.append(_entry("gpatents", "miss", "zero_hits",
                                             scraping=True, elapsed_ms=elapsed))
            except Exception as e:  # noqa: BLE001
                provenance.append(_entry("gpatents", "error", _error_reason(e),
                                         scraping=True,
                                         elapsed_ms=int((time.monotonic() - t0) * 1000)))
        if hit is None:
            return _envelope(
                False, [], None, provenance, [], None,
                error_code="ALL_SOURCES_MISS",
                message="全部來源(含授權尾級)皆未命中;請調整檢索軸(換分類/放寬日期/改關鍵字)",
            )

    source, records, total = hit
    return _envelope(True, records, source, provenance,
                     list(SOURCE_GAPS.get(source, [])), total)
