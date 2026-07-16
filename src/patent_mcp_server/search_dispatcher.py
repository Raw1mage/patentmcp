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
from datetime import date, timedelta
from dataclasses import dataclass, field, replace
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
    # date normalization: GPSS ID / EPO pd / gpatents all expect bare YYYYMMDD.
    # Callers naturally pass ISO 2023-01-01; an un-stripped hyphen makes GPSS
    # return zero_hits and silently falls the ladder through to EPO's global
    # index (wrong-jurisdiction pollution). Normalize once, at the single entry.
    spec.date_from = _normalize_date(spec.date_from)
    spec.date_to = _normalize_date(spec.date_to)
    if spec.databases:
        spec.databases = [str(d).strip() for d in spec.databases if str(d).strip()]
        spec.databases = spec.databases or None
    return spec


# GPSS-exclusive database prefixes: these jurisdictions are only served by the
# TIPO GPSS backend. EPO's global index does NOT honor a `databases` filter, so
# when a caller scopes strictly to these, an EPO fallthrough would return
# out-of-jurisdiction hits (e.g. a PL/EP case) — worse than an honest miss.
_GPSS_ONLY_COUNTRIES = frozenset({"CN", "TW"})


def _normalize_date(v: Optional[str]) -> Optional[str]:
    """Coerce a date bound to bare YYYYMMDD (strip -, /, whitespace).

    Accepts '2023-01-01', '2023/01/01', '20230101'. Returns None for empty /
    unparseable input rather than passing a malformed token to the backends.
    """
    if not v:
        return None
    digits = re.sub(r"\D", "", str(v))
    return digits or None


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


# ── classification-axis bulk export (plans/patentmcp_classification-bulk-export) ──
# Distinct semantics from the relevance ladder above: PURE classification axis
# (ipc/cpc/uspc), large expQty with auto-pagination, forced full expFld, and an
# official MISS is a true zero — NEVER falls back to the scraper tail (DD-5).

BULK_EXPORT_MAX = 5000          # num hard ceiling (DD-2, TIPO quota guard)
_BULK_PAGE = 200                # per-page expQty (stable value; paginate to reach num)
_BULK_PAGE_RETRIES = 3          # per-page transient-error retries before giving up (no source fallback)
_BULK_PAGE_BACKOFF_BASE = 2.0   # exp-backoff base seconds: 2s / 4s / 8s
_BULK_FIELDS = "PN,AN,ID,AD,PR,TI,AB,CL,IC,CS,UC,PA,IN"  # forced full fields (DD-3)


async def _bulk_pull_gpss(
    spec: QuerySpec, gpss_client: Any,
) -> Tuple[List[Dict[str, Any]], Optional[int], List[Dict[str, Any]]]:
    """Auto-paginate a PURE classification-axis GPSS query to exhaustion or num.

    Shared internal used by patent_bulk_export (and reusable by any relevance
    path that needs to exhaust an axis — DD-1). Returns (records, total,
    per-page provenance). keyword is NOT combined as an AND narrowing (DD-4);
    an empty first page means a true zero (caller must NOT fall back — DD-5).
    """
    from patent_mcp_server.gpss.client import GPSSCondition

    conditions: List[Any] = []
    if spec.cpc:
        conditions.append(GPSSCondition("CS", spec.cpc))
    if spec.ipc:
        conditions.append(GPSSCondition("IC", spec.ipc))
    if spec.uspc:
        conditions.append(GPSSCondition("UC", spec.uspc))
    # date/databases are soft filters; keyword is DELIBERATELY NOT added (DD-4).
    if spec.date_from or spec.date_to:
        conditions.append(GPSSCondition("ID", f"{spec.date_from or ''}:{spec.date_to or ''}"))

    target = min(spec.num, BULK_EXPORT_MAX)
    records: List[Dict[str, Any]] = []
    prov: List[Dict[str, Any]] = []
    skip = spec.skip
    total: Optional[int] = None
    while len(records) < target:
        cur = min(_BULK_PAGE, target - len(records))
        t0 = time.monotonic()
        res = await gpss_client.search(
            conditions=conditions, databases=spec.databases,
            fields=_BULK_FIELDS, num=cur, skip=skip, fmt="json",
        )
        elapsed = int((time.monotonic() - t0) * 1000)
        if not res.get("success"):
            # status=success + boilerplate message == "no record found" → true zero
            if res.get("status") == "success":
                prov.append(_entry("gpss", "miss", "zero_hits", elapsed_ms=elapsed))
                if not records:
                    return [], _to_int(res.get("total")) or 0, prov
                break
            if records:
                prov.append(_entry("gpss", "error",
                                   _error_reason(Exception(str(res.get("error") or res.get("message")))),
                                   elapsed_ms=elapsed))
                logger.warning("bulk_export pagination failed at skip=%d: %s",
                               skip, res.get("error") or res.get("message"))
                break
            raise BackendError(str(res.get("error") or res.get("message") or "GPSS bulk export failed"))
        page = _st.gpss_to_records(res)
        total = _to_int(res.get("total"))
        if not page:
            prov.append(_entry("gpss", "miss" if not records else "hit",
                               "axis_exhausted", elapsed_ms=elapsed))
            break
        prov.append(_entry("gpss", "hit", f"page skip={skip} n={len(page)}",
                           elapsed_ms=elapsed))
        records.extend(page)
        skip += len(page)
        # `skip` is the absolute cursor (already advanced past this page); the
        # axis is exhausted once the cursor reaches the reported total.
        if total is not None and skip >= total:
            break
        await asyncio.sleep(1.0)
    return records[:target], total, prov


async def bulk_export(spec: QuerySpec, *, gpss_client: Any) -> Dict[str, Any]:
    """Classification-axis bulk export entry (data-schema.json bulk_export_result).

    Requires at least one classification axis (ipc/cpc/uspc). GPSS-only: an
    official miss is a true zero and NEVER falls back to the scraper (DD-5).
    Returns {success, records[], source, provenance[], gaps[], total,
    error_code?}.
    """
    if not (spec.ipc or spec.cpc or spec.uspc):
        return _envelope(
            False, [], None, [], [], None, error_code="INVALID_PARAMS",
            message="分類軸批次匯出需至少一個分類軸 (ipc/cpc/uspc)",
        )
    if not gpss_client.configured():
        return _envelope(
            False, [], None,
            [_entry("gpss", "skipped", "not_configured")], [], None,
            error_code="GPSS_NOT_CONFIGURED",
            message="批次匯出僅走 TIPO GPSS 官方端點，需設 GPSS_USER_CODE",
        )
    try:
        records, total, prov = await _bulk_pull_gpss(spec, gpss_client)
    except BackendError as e:
        return _envelope(
            False, [], None, [_entry("gpss", "error", _error_reason(e))],
            [], None, error_code="GPSS_ERROR", message=str(e),
        )
    if not records:
        # true zero — NO scraper fallback (DD-5)
        return _envelope(
            True, [], "gpss", prov, list(SOURCE_GAPS.get("gpss", [])), total or 0,
        )
    return _envelope(True, records, "gpss", prov,
                     list(SOURCE_GAPS.get("gpss", [])), total)


# ── keyword-aware bulk harvest ──────────────────────────────────────
# Distinct from bulk_export: this DELIBERATELY keeps the keyword + field-level
# `not (...)` narrowing (bulk_export drops it per DD-4). Use when a research
# harvest's relevance hinges on a keyword recall-set + NOT exclusion (e.g. the
# anomaly-noncontact prior-art first-formula: 3-axis OR AND detection AND
# not(industrial-scene words)) that a pure classification axis cannot express.
# Same server-side auto-pagination as bulk_export → no dialog turn-budget burn.
# GPSS-only, official miss is a true zero, NEVER falls back to the scraper.

async def _bulk_pull_gpss_kw(
    spec: QuerySpec, gpss_client: Any,
) -> Tuple[List[Dict[str, Any]], Optional[int], List[Dict[str, Any]]]:
    """Auto-paginate a keyword-AND-classification GPSS query to exhaustion or num.

    Identical pagination contract to _bulk_pull_gpss, but the keyword condition
    IS added (the whole point). date is normalized upstream (normalize_query),
    so ID is bare YYYYMMDD here. An empty first page is a true zero (caller must
    NOT fall back). Returns (records, total, per-page provenance).
    """
    from patent_mcp_server.gpss.client import GPSSCondition

    conditions: List[Any] = []
    if spec.cpc:
        conditions.append(GPSSCondition("CS", spec.cpc))
    if spec.ipc:
        conditions.append(GPSSCondition("IC", spec.ipc))
    if spec.uspc:
        conditions.append(GPSSCondition("UC", spec.uspc))
    if spec.keyword:
        conditions.append(GPSSCondition(spec.keyword_field or "TI/AB", spec.keyword))
    if spec.inventor_country:
        conditions.append(GPSSCondition("IY", spec.inventor_country))
    if spec.applicant:
        conditions.append(GPSSCondition("AX", spec.applicant))
    if spec.date_from or spec.date_to:
        conditions.append(GPSSCondition("ID", f"{spec.date_from or ''}:{spec.date_to or ''}"))

    target = min(spec.num, BULK_EXPORT_MAX)
    records: List[Dict[str, Any]] = []
    prov: List[Dict[str, Any]] = []
    skip = spec.skip
    total: Optional[int] = None
    while len(records) < target:
        cur = min(_BULK_PAGE, target - len(records))
        # Per-page transient-error retry with exponential backoff. GPSS
        # intermittently returns non-JSON (rate-limit / transient) for a page
        # whose data is otherwise fetchable (verified: patent_search on the same
        # skip succeeds). Retry the SAME page up to _BULK_PAGE_RETRIES times
        # before giving up, so one transient hiccup no longer truncates the
        # whole harvest. Still GPSS-only, still true-zero semantics — no source
        # fallback is introduced.
        res: Dict[str, Any] = {}
        elapsed = 0
        page_ok = False
        for attempt in range(_BULK_PAGE_RETRIES + 1):
            t0 = time.monotonic()
            res = await gpss_client.search(
                conditions=conditions, databases=spec.databases,
                fields=_BULK_FIELDS, num=cur, skip=skip, fmt="json",
            )
            elapsed = int((time.monotonic() - t0) * 1000)
            if res.get("success"):
                page_ok = True
                break
            # An official zero-hit is NOT a transient error — do not retry.
            if res.get("status") == "success":
                break
            if attempt < _BULK_PAGE_RETRIES:
                backoff = _BULK_PAGE_BACKOFF_BASE * (2 ** attempt)
                logger.warning(
                    "bulk_harvest transient error at skip=%d (attempt %d/%d): %s — retrying in %.1fs",
                    skip, attempt + 1, _BULK_PAGE_RETRIES, res.get("error") or res.get("message"), backoff,
                )
                _raw = res.get("raw")
                prov.append(_entry("gpss", "retry",
                                   f"skip={skip} attempt={attempt + 1}/{_BULK_PAGE_RETRIES} "
                                   f"{_error_reason(Exception(str(res.get('error') or res.get('message'))))}"
                                   + (f" | raw[:200]={_raw[:200]!r}" if _raw else ""),
                                   elapsed_ms=elapsed))
                await asyncio.sleep(backoff)
        if not page_ok:
            if res.get("status") == "success":
                prov.append(_entry("gpss", "miss", "zero_hits", elapsed_ms=elapsed))
                if not records:
                    return [], _to_int(res.get("total")) or 0, prov
                break
            if records:
                _raw = res.get("raw")
                prov.append(_entry("gpss", "error",
                                   f"skip={skip} exhausted {_BULK_PAGE_RETRIES} retries: "
                                   f"{_error_reason(Exception(str(res.get('error') or res.get('message'))))}"
                                   + (f" | raw[:300]={_raw[:300]!r}" if _raw else ""),
                                   elapsed_ms=elapsed))
                logger.warning("bulk_harvest pagination failed at skip=%d after %d retries: %s",
                               skip, _BULK_PAGE_RETRIES, res.get("error") or res.get("message"))
                break
            raise BackendError(str(res.get("error") or res.get("message") or "GPSS bulk harvest failed"))
        page = _st.gpss_to_records(res)
        total = _to_int(res.get("total"))
        if not page:
            prov.append(_entry("gpss", "miss" if not records else "hit",
                               "axis_exhausted", elapsed_ms=elapsed))
            break
        prov.append(_entry("gpss", "hit", f"page skip={skip} n={len(page)}",
                           elapsed_ms=elapsed))
        records.extend(page)
        skip += len(page)
        if total is not None and skip >= total:
            break
        await asyncio.sleep(1.0)
    return records[:target], total, prov


async def bulk_harvest(spec: QuerySpec, *, gpss_client: Any) -> Dict[str, Any]:
    """Keyword-aware bulk harvest entry (mirrors bulk_export envelope).

    Requires at least one hard axis (keyword OR a classification axis). GPSS-only:
    an official miss is a true zero and NEVER falls back to the scraper. Unlike
    bulk_export, the keyword + field-level not(...) narrowing is preserved.
    """
    if not (spec.keyword or spec.ipc or spec.cpc or spec.uspc):
        return _envelope(
            False, [], None, [], [], None, error_code="INVALID_PARAMS",
            message="批次收割需至少一個檢索軸 (keyword/ipc/cpc/uspc)",
        )
    if not gpss_client.configured():
        return _envelope(
            False, [], None,
            [_entry("gpss", "skipped", "not_configured")], [], None,
            error_code="GPSS_NOT_CONFIGURED",
            message="批次收割僅走 TIPO GPSS 官方端點，需設 GPSS_USER_CODE",
        )
    try:
        records, total, prov = await _bulk_pull_gpss_kw(spec, gpss_client)
    except BackendError as e:
        # Condition-length wall (DD-10/DD-11): the WHOLE boolean was too long a
        # STRING for GPSS. Split the widest positive OR-group and union the
        # shards' hits (recall-preserving; NOT groups stay byte-identical).
        if spec.keyword and _GPSS_CONDITION_LENGTH_MARKER in str(e):
            return await _bulk_harvest_sharded(spec, gpss_client, str(e))
        return _envelope(
            False, [], None, [_entry("gpss", "error", _error_reason(e))],
            [], None, error_code="GPSS_ERROR", message=str(e),
        )
    if not records:
        return _envelope(
            True, [], "gpss", prov, list(SOURCE_GAPS.get("gpss", [])), total or 0,
        )
    return _envelope(True, records, "gpss", prov,
                     list(SOURCE_GAPS.get("gpss", [])), total)


# GPSS caps the search-condition STRING; the exact byte ceiling is opaque, so we
# probe with a conservative length threshold. A shard whose keyword is under this
# is assumed to clear the wall; if a shard STILL trips it at harvest time, the
# recursive splitter is re-driven by the live error (belt-and-suspenders).
_GPSS_CONDITION_LENGTH_LIMIT = 900  # chars; tuned below the observed TIPO ceiling


async def _bulk_harvest_sharded(
    spec: QuerySpec, gpss_client: Any, trigger_msg: str,
) -> Dict[str, Any]:
    """Split an over-long GPSS keyword and union the per-shard harvests.

    Deterministic set-algebra recovery (DD-11): bisect the widest positive
    OR-group into shards whose keyword strings each clear the condition-length
    wall, harvest each via the SAME _bulk_pull_gpss_kw, then union records by
    `pubno` (first occurrence wins). NOT groups are byte-identical across shards
    so no patent is silently dropped. Irreducible → CONDITION_LENGTH_IRREDUCIBLE.
    """
    def _fits(kw: str) -> bool:
        return len(kw) <= _GPSS_CONDITION_LENGTH_LIMIT

    try:
        shard_queries = _shard_gpss_query(spec.keyword, _fits)
    except ValueError:
        return _envelope(
            False, [], None,
            [_entry("gpss", "error", "condition_length_irreducible")],
            [], None, error_code="CONDITION_LENGTH_IRREDUCIBLE",
            message=("檢索條件字串超過 GPSS 上限且無法再分（單一 OR 詞 + 全 AND/NOT "
                     "群仍超長）；請縮短同義詞群或改用分類軸。原始錯誤：" + trigger_msg),
        )

    union: Dict[str, Dict[str, Any]] = {}
    prov: List[Dict[str, Any]] = [
        _entry("gpss", "shard", f"condition-length wall → {len(shard_queries)} shards")
    ]
    shard_meta: List[Dict[str, Any]] = []
    union_landed = 0
    grand_total = 0
    for frag in shard_queries:
        shard_spec = replace(spec, keyword=frag)
        try:
            recs, s_total, s_prov = await _bulk_pull_gpss_kw(shard_spec, gpss_client)
        except BackendError as e:
            # A shard STILL over the wall (threshold under-estimated the true
            # ceiling) → honest fail-fast rather than a silent partial union.
            if _GPSS_CONDITION_LENGTH_MARKER in str(e):
                return _envelope(
                    False, [], None,
                    [_entry("gpss", "error",
                            f"shard still over condition length: {frag[:80]!r}")],
                    [], None, error_code="CONDITION_LENGTH_IRREDUCIBLE",
                    message=("分片後子查詢仍超過 GPSS 條件長度上限，請縮短同義詞群。"
                             "子查詢片段：" + frag),
                )
            return _envelope(
                False, [], None, [_entry("gpss", "error", _error_reason(e))],
                [], None, error_code="GPSS_ERROR", message=str(e),
            )
        prov.extend(s_prov)
        landed = 0
        for rec in recs:
            pubno = rec.get("pubno")
            key = pubno if pubno else id(rec)
            if key not in union:
                union[key] = rec
                landed += 1
        union_landed += landed
        grand_total += s_total or 0
        shard_meta.append({
            "query_frag": frag,
            "total": s_total or 0,
            "landed": landed,
        })

    records = list(union.values())
    env = _envelope(
        True, records, "gpss", prov,
        list(SOURCE_GAPS.get("gpss", [])), grand_total,
    )
    env["sharding"] = {
        "applied": True,
        "shards": shard_meta,
        "union_total": grand_total,
        "union_landed": len(records),
    }
    return env


# ── GPSS query-slicing (DD-10/DD-11; BR_20260715) ───────────────────
# TIPO GPSS enforces a hard limit on the search-condition STRING length; a long
# landscape-recall boolean (dozens of OR synonyms) trips it with
# `GPSS_ERROR: Exceeded search condition length`. POST cannot bypass it (proven
# 2026-07-15: GPSS reads only the URL query string, body is ignored — DD-10), so
# the only fix is to make the query STRING shorter: split it and union the hits.
#
# The split is a deterministic set-algebra operation, NOT a heuristic. A GPSS
# keyword is a top-level AND of groups: positive OR-groups joined by and/or, and
# NOT groups joined by `not`. We bisect ONLY the widest positive OR-group into
# Bx / By and keep everything else — every other positive group AND every NOT
# group — byte-identical in both shards, because:
#     (Bx ∪ By) ∩ C ∩ ¬D  =  (Bx ∩ C ∩ ¬D) ∪ (By ∩ C ∩ ¬D)     (distributive)
# holds, but splitting a NOT group is NOT recall-preserving:
#     ¬(D1 ∪ D2) = ¬D1 ∩ ¬D2  ≠  ¬D1 ∪ ¬D2
# so a split NOT group would silently drop patents. NOT groups are frozen.

_GPSS_CONDITION_LENGTH_MARKER = "Exceeded search condition length"
_GPSS_SHARD_DEPTH_CAP = 6  # bisection depth cap (aligns with DD-9 EPO slice cap)


def _split_top_level(tokens: List[str]) -> List[Tuple[str, List[str]]]:
    """Split a token stream into top-level (connector, group-tokens) segments.

    A "group" is either a parenthesized run or a bare term at paren-depth 0.
    The connector is the boolean operator (`and`/`or`/`not`) that precedes the
    group at depth 0; the first group's connector is "" (leading). Operators and
    parentheses INSIDE a group stay with that group's tokens (untouched).
    """
    segments: List[Tuple[str, List[str]]] = []
    pending_conn = ""
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        low = tok.lower()
        if low in ("and", "or", "not") and _paren_depth(tokens[:i]) == 0:
            pending_conn = low
            i += 1
            continue
        if tok == "(":
            depth = 0
            grp: List[str] = []
            while i < n:
                t = tokens[i]
                grp.append(t)
                if t == "(":
                    depth += 1
                elif t == ")":
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                i += 1
            segments.append((pending_conn, grp))
            pending_conn = ""
        else:
            segments.append((pending_conn, [tok]))
            pending_conn = ""
            i += 1
    return segments


def _paren_depth(tokens: List[str]) -> int:
    return sum(1 if t == "(" else -1 if t == ")" else 0 for t in tokens)


def _group_terms(grp_tokens: List[str]) -> List[str]:
    """Extract the OR-joined TERMS of a positive group (strip outer parens/ops)."""
    inner = grp_tokens
    if inner and inner[0] == "(" and inner[-1] == ")":
        inner = inner[1:-1]
    return [t for t in inner if t.lower() not in ("and", "or", "not")
            and t not in ("(", ")")]


def _render_group(terms: List[str]) -> str:
    """Render a list of terms back into a parenthesized OR-group string."""
    if len(terms) == 1:
        return terms[0]
    return "(" + " or ".join(terms) + ")"


def _parse_gpss_query(keyword: str) -> Dict[str, Any]:
    """Parse a GPSS boolean keyword into positive vs NOT top-level groups.

    Returns {positive_groups: [[terms]...], not_groups: [[terms]...],
    raw_structure: [(connector, group_tokens)...]}. positive_groups carries the
    OR-terms of each and/or-joined group; not_groups carries the terms of each
    `not`-joined group (kept for classification only — NOT groups are never
    split). raw_structure preserves the exact top-level segmentation so the
    sharder can rebuild the query with a single group swapped.
    """
    raw = re.findall(r'"[^"]*"|\(|\)|[^()\s]+', keyword or "")
    segments = _split_top_level(raw)
    positive_groups: List[List[str]] = []
    not_groups: List[List[str]] = []
    for conn, grp in segments:
        terms = _group_terms(grp)
        if conn == "not":
            not_groups.append(terms)
        else:
            positive_groups.append(terms)
    return {
        "positive_groups": positive_groups,
        "not_groups": not_groups,
        "raw_structure": segments,
    }


def _render_query(segments: List[Tuple[str, List[str]]]) -> str:
    """Rebuild a keyword string from top-level (connector, group_tokens)."""
    parts: List[str] = []
    for conn, grp in segments:
        if conn:
            parts.append(conn)
        parts.append(" ".join(grp))
    out = " ".join(p for p in parts if p)
    out = out.replace("( ", "(").replace(" )", ")")
    return out


def _shard_gpss_query(keyword: str, fits_fn: Any) -> List[str]:
    """Split an over-long GPSS keyword into shards that each pass `fits_fn`.

    `fits_fn(query_str) -> bool` is True when the query fits the condition-length
    limit (injectable for tests; production uses a length threshold or a live
    retry probe). Bisects ONLY the widest positive OR-group into two halves,
    keeping every other positive group AND all NOT groups byte-identical in both
    shards (recall-preserving; DD-11). Recurses on any shard still over-long
    (depth cap _GPSS_SHARD_DEPTH_CAP). Raises ValueError with sentinel
    "CONDITION_LENGTH_IRREDUCIBLE" when even a single OR-term + all AND/NOT
    groups still exceeds the limit.
    """
    def _rec(kw: str, depth: int) -> List[str]:
        if fits_fn(kw):
            return [kw]
        if depth >= _GPSS_SHARD_DEPTH_CAP:
            raise ValueError("CONDITION_LENGTH_IRREDUCIBLE")
        parsed = _parse_gpss_query(kw)
        segments = parsed["raw_structure"]
        # Pick the positive group (connector != "not") with the most OR-terms.
        widest_idx = -1
        widest_terms: List[str] = []
        for idx, (conn, grp) in enumerate(segments):
            if conn == "not":
                continue
            terms = _group_terms(grp)
            if len(terms) > len(widest_terms):
                widest_terms = terms
                widest_idx = idx
        # Irreducible: no positive group has >1 term to bisect.
        if widest_idx < 0 or len(widest_terms) <= 1:
            raise ValueError("CONDITION_LENGTH_IRREDUCIBLE")
        mid = len(widest_terms) // 2
        left, right = widest_terms[:mid], widest_terms[mid:]
        conn, _grp = segments[widest_idx]
        shards: List[str] = []
        for half in (left, right):
            new_segments = list(segments)
            new_segments[widest_idx] = (conn, _tokenize_group(_render_group(half)))
            shard_kw = _render_query(new_segments)
            shards.extend(_rec(shard_kw, depth + 1))
        return shards

    return _rec(keyword, 0)


def _tokenize_group(group_str: str) -> List[str]:
    """Tokenize a rendered group string back into tokens (parens/phrases/terms)."""
    return re.findall(r'"[^"]*"|\(|\)|[^()\s]+', group_str)


def _keyword_to_cql(keyword: str, field: str = "txt") -> str:
    """Translate a GPSS-style boolean keyword expression into EPO CQL.

    GPSS keyword syntax mixes bare terms, quoted phrases, parentheses and the
    boolean operators AND / OR / NOT. EPO OPS CQL expresses the same thing but
    each search TERM must carry its own field prefix, e.g.
        (radar OR mmwave) AND (fall OR "vital sign")
    becomes
        (txt=radar or txt=mmwave) and (txt=fall or txt="vital sign")

    The previous implementation wrapped the whole string in a single
    ``txt="..."`` phrase field, which produced invalid CQL whenever a boolean
    operator was present (EPO returned parse error). This tokenizer keeps
    phrase-internal spaces quoted while turning operator spaces into real CQL
    boolean joins.
    """
    if not keyword:
        return ""
    # Tokenize: quoted phrases, parens, and bare runs (which may glue to parens).
    raw = re.findall(r'"[^"]*"|\(|\)|[^()\s]+', keyword)
    ops = {"and", "or", "not"}
    out: List[str] = []
    for tok in raw:
        low = tok.lower()
        if tok in ("(", ")"):
            out.append(tok)
        elif low in ops:
            out.append(low)
        elif tok.startswith('"') and tok.endswith('"'):
            # quoted phrase -> keep the quotes as a CQL phrase term
            inner = tok[1:-1].strip()
            if inner:
                out.append(f'{field}="{inner}"')
        else:
            out.append(f"{field}={tok}")
    # Join: no space before ')' or after '(' keeps CQL tidy; simple join is valid.
    cql = " ".join(out)
    cql = cql.replace("( ", "(").replace(" )", ")")
    return cql


async def _run_epo(spec: QuerySpec, epo_client: Any) -> Tuple[List[Dict[str, Any]], Optional[int], Optional[str]]:
    cql = _epo_build_cql(spec)

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


# ── EPO server-side bulk harvest (mirrors GPSS bulk_harvest) ────────
# EPO OPS caps a single search page at 100 refs and skip at ~2000; each ref
# needs a second-stage biblio under the 15/min throttle. A dialog-driven full
# harvest therefore burns many manual num/skip round-trips (and each num=2000
# call times out on the biblio fan-out). This loop paginates + fetches biblio
# server-side so one call lands a whole date slice, capped at the OPS skip wall.
_EPO_SEARCH_PAGE = 100          # OPS per-search-page ref ceiling
_EPO_SKIP_WALL = 2000           # OPS deep-paging wall (skip>=2000 -> HTTP 400)
_EPO_PAGE_RETRIES = 2           # transient (429/500) retries per page
_EPO_PAGE_BACKOFF_BASE = 4.0    # OPS throttle-friendly backoff: 4s / 8s
_EPO_BIBLIO_SLEEP = 0.2         # inter-biblio spacing (stay under 15/min bursts)
# MCP-timeout-safe per-call biblio fan-out cap (BR_20260710)。單 call 內 biblio
# fan-out 受 OPS 15/min 節流:100 refs × ~4s ≈ 7min,遠超 MCP transport ~2min →
# call 被切、server 迴圈終止、無法靠重發推進(每次從同 skip 重來燒節流額度)。
# 實測(BR workaround)num≤20 逐頁驅動決定性有效(total 934 全程零逾時)。
# 把單 call 的 target cap 在 20:單 call ~1.5min 內乾淨返回,靠已存在的
# next_skip/exhausted 讓 caller 逐頁續跑。caller 顯式帶更大 num 時仍以此 cap
# 分段,不改 next_skip 續跑語義。
_EPO_CALL_BIBLIO_CAP = 20


def _epo_build_cql(spec: QuerySpec) -> str:
    """Build the EPO CQL string from a QuerySpec (shared by _run_epo + harvest)."""
    parts: List[str] = []
    if spec.cpc:
        parts.append(f"cpc={spec.cpc}")
    if spec.ipc:
        parts.append(f"ic={spec.ipc}")
    if spec.keyword:
        cql_kw = _keyword_to_cql(spec.keyword)
        if cql_kw:
            parts.append(cql_kw)
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
    return " and ".join(parts)


async def _bulk_pull_epo(
    spec: QuerySpec, epo_client: Any,
    absorb_cb: Optional[Any] = None,
) -> Tuple[List[Dict[str, Any]], Optional[int], List[Dict[str, Any]], int]:
    """Auto-paginate an EPO CQL query, fetching biblio for every ref, until the
    target num, the total, or the OPS skip wall (~2000) is reached.

    Returns (records, total, per-page provenance, next_skip). A per-page
    transient error is retried with backoff; a hard failure stops the harvest
    but keeps whatever landed (no source fallback — EPO-only, honest partial).

    absorb_cb: optional callable(records_page) invoked AFTER each page's biblio
    fan-out completes, so rows land in patentdb incrementally — a client-side
    timeout on the biblio fan-out (hundreds of seconds for a full slice) no
    longer discards everything. `next_skip` lets the caller resume the pull.
    """
    cql = _epo_build_cql(spec)
    if not cql:
        raise BackendError("EPO bulk harvest needs at least one axis")

    # MCP-timeout-safe:單 call 的 biblio fan-out 量 cap 在 _EPO_CALL_BIBLIO_CAP
    # (BR_20260710)。caller 帶更大 num 時,靠 next_skip 逐 call 續跑推進,而非
    # 單 call 內一次拉完撞 transport timeout。
    target = min(spec.num, _EPO_CALL_BIBLIO_CAP, _EPO_SKIP_WALL)
    records: List[Dict[str, Any]] = []
    prov: List[Dict[str, Any]] = []
    skip = spec.skip
    total: Optional[int] = None
    while len(records) < target and skip < _EPO_SKIP_WALL:
        cur = min(_EPO_SEARCH_PAGE, target - len(records), _EPO_SKIP_WALL - skip)
        res: Dict[str, Any] = {}
        page_ok = False
        elapsed = 0
        for attempt in range(_EPO_PAGE_RETRIES + 1):
            t0 = time.monotonic()
            res = await epo_client.search(cql, range_=f"{skip + 1}-{skip + cur}")
            elapsed = int((time.monotonic() - t0) * 1000)
            if res.get("success"):
                page_ok = True
                break
            if attempt < _EPO_PAGE_RETRIES:
                backoff = _EPO_PAGE_BACKOFF_BASE * (2 ** attempt)
                logger.warning(
                    "epo bulk_harvest transient error at skip=%d (attempt %d/%d): %s — retrying in %.1fs",
                    skip, attempt + 1, _EPO_PAGE_RETRIES, res.get("error"), backoff,
                )
                prov.append(_entry("epo", "retry",
                                   f"skip={skip} attempt={attempt + 1}/{_EPO_PAGE_RETRIES} "
                                   f"{res.get('error')}", elapsed_ms=elapsed))
                await asyncio.sleep(backoff)
        if not page_ok:
            if records:
                prov.append(_entry("epo", "error",
                                   f"skip={skip} exhausted {_EPO_PAGE_RETRIES} retries: {res.get('error')}",
                                   elapsed_ms=elapsed))
                logger.warning("epo bulk_harvest pagination failed at skip=%d: %s",
                               skip, res.get("error"))
                break
            raise BackendError(str(res.get("error") or "EPO bulk harvest failed"))
        pubs = res.get("results") or []
        total = _to_int(res.get("total"))
        if not pubs:
            prov.append(_entry("epo", "miss" if not records else "hit",
                               "axis_exhausted", elapsed_ms=elapsed))
            break
        prov.append(_entry("epo", "hit", f"page skip={skip} n={len(pubs)}",
                           elapsed_ms=elapsed))
        page_records: List[Dict[str, Any]] = []
        for pub in pubs:
            try:
                b = await epo_client.biblio(pub)
            except Exception as e:  # noqa: BLE001 — one biblio miss must not kill the page
                logger.warning("EPO biblio failed for %s: %s", pub, e)
                b = {}
            page_records.append(_st.epo_biblio_to_record(pub, b if b.get("success") else {}))
            await asyncio.sleep(_EPO_BIBLIO_SLEEP)
        # Land this page NOW — a later client timeout won't discard it.
        if absorb_cb is not None and page_records:
            try:
                absorb_cb(page_records)
            except Exception as e:  # noqa: BLE001 — absorb must never break the pull
                logger.warning("EPO bulk_harvest per-page absorb failed: %s", e)
        records.extend(page_records)
        skip += len(pubs)
        if total is not None and skip >= total:
            break
    return records[:target], total, prov, skip


async def epo_bulk_harvest(
    spec: QuerySpec, *, epo_client: Any, absorb_cb: Optional[Any] = None,
) -> Dict[str, Any]:
    """EPO server-side bulk harvest entry (mirrors gpss bulk_harvest envelope).

    Requires at least one hard axis. EPO-only: a miss is a true zero, NEVER a
    scraper fallback. Paginates + fetches biblio server-side up to num / total /
    the OPS skip wall (~2000). absorb_cb lands each page incrementally so a
    client-side timeout on the biblio fan-out keeps whatever already landed;
    the envelope carries `next_skip` for resuming.

    Per-call cap (BR_20260710): each call's biblio fan-out is capped at
    _EPO_CALL_BIBLIO_CAP (20) refs so one call finishes well under the MCP
    transport timeout (~2min). A larger `num` is harvested across multiple
    calls via `next_skip` — the envelope flags `page_capped=true` when this
    call returned early on the cap (not exhaustion), so the caller knows to
    resume with next_skip instead of mistaking it for total-complete.
    """
    if not (spec.keyword or spec.ipc or spec.cpc or spec.uspc or spec.applicant):
        return _envelope(
            False, [], None, [], [], None, error_code="INVALID_PARAMS",
            message="批次收割需至少一個檢索軸 (keyword/ipc/cpc/uspc/applicant)",
        )
    if not epo_client.configured():
        return _envelope(
            False, [], None,
            [_entry("epo", "skipped", "not_configured")], [], None,
            error_code="EPO_NOT_CONFIGURED",
            message="EPO 批次收割需設 EPO_CONSUMER_KEY/SECRET",
        )
    try:
        records, total, prov, next_skip = await _bulk_pull_epo(
            spec, epo_client, absorb_cb=absorb_cb)
    except BackendError as e:
        return _envelope(
            False, [], None, [_entry("epo", "error", _error_reason(e))],
            [], None, error_code="EPO_ERROR", message=str(e),
        )
    env = _envelope(True, records, "epo", prov,
                    list(SOURCE_GAPS.get("epo", [])),
                    total if records else (total or 0))
    env["next_skip"] = next_skip
    env["exhausted"] = bool(total is not None and next_skip >= total) or (
        next_skip >= _EPO_SKIP_WALL)
    # 標記本 call 是否因 per-call cap 提前返回(未 exhausted 但 records 達 cap):
    # 讓 caller 知道要帶 next_skip 再呼叫一次(而非誤判 total 已撈完)。
    env["page_capped"] = bool(
        not env["exhausted"] and len(records) >= _EPO_CALL_BIBLIO_CAP)
    env["call_biblio_cap"] = _EPO_CALL_BIBLIO_CAP
    return env


# ── EPO auto date-slicing (DD-8/DD-9, issue_20260710) ───────────────
# OPS caps deep paging at skip=2000 (HTTP 400 beyond). A query whose total
# exceeds the wall CANNOT be pulled in one continuation chain — it must be split
# by publication-date into slices each < wall, then each slice pulled on its own
# (in-slice next_skip continuation). This planner ONLY count-probes (num=1, zero
# biblio fan-out) and returns a slice plan; it NEVER pulls records. The caller
# harvests each slice via patent_bulk(source="epo", date_from=.., date_to=..).
_EPO_SLICE_DEPTH_CAP = 6        # year→half→quarter→month→half-month→week (DD-9)
_EPO_SLICE_PROBE_CAP = 32       # total count-probe search calls (DD-9)
_EPO_SLICE_SUM_TOL = 0.05       # leaf-sum vs parent-total drift tolerance (5%)


def _parse_ymd(v: str) -> date:
    """Parse a bare YYYYMMDD token into a date (normalize_query already stripped
    separators, so this sees 8 digits)."""
    return date(int(v[0:4]), int(v[4:6]), int(v[6:8]))


def _fmt_ymd(d: date) -> str:
    return f"{d.year:04d}{d.month:02d}{d.day:02d}"


async def _epo_probe_total(
    spec: QuerySpec, epo_client: Any,
    date_from: Optional[str], date_to: Optional[str],
    prov: List[Dict[str, Any]],
) -> int:
    """Count-probe one date window: a num=1 OPS search returning only `total`
    (zero biblio fan-out). Appends a provenance entry; raises BackendError on a
    hard search failure (fail-fast, no fallback)."""
    probe_spec = QuerySpec(
        cpc=spec.cpc, ipc=spec.ipc, uspc=spec.uspc,
        keyword=spec.keyword, keyword_field=spec.keyword_field,
        applicant=spec.applicant, pub_number=spec.pub_number,
        date_from=date_from, date_to=date_to,
    )
    cql = _epo_build_cql(probe_spec)
    if not cql:
        raise BackendError("EPO slice_plan needs at least one axis")
    t0 = time.monotonic()
    res = await epo_client.search(cql, range_="1-1")
    elapsed = int((time.monotonic() - t0) * 1000)
    if not res.get("success"):
        prov.append(_entry("epo", "error",
                           f"probe {date_from}..{date_to}: {res.get('error')}",
                           elapsed_ms=elapsed))
        raise BackendError(str(res.get("error") or "EPO slice probe failed"))
    total = _to_int(res.get("total")) or 0
    prov.append(_entry("epo", "hit",
                       f"probe {date_from or '*'}..{date_to or '*'} total={total}",
                       elapsed_ms=elapsed))
    return total


async def epo_slice_plan(
    spec: QuerySpec, *, epo_client: Any,
) -> Dict[str, Any]:
    """Plan EPO publication-date slices so each slice's total stays under the OPS
    skip wall (DD-8/DD-9). Count-probe only — ZERO records pulled.

    Contract:
      • probe母數: num=1 search on spec's CQL → total (no biblio fan-out).
      • total ≤ _EPO_SKIP_WALL → single slice (original date range or none).
      • total > wall and no date range (date_from/date_to both absent) →
        error_code=DATE_RANGE_REQUIRED (never guess a full-history span, 天條).
      • total > wall with a date range → recursively BISECT the date interval on
        mutually-exclusive cut points (left to=D, right from=D+1 day) until each
        leaf total < wall. YYYYMMDD arithmetic via datetime.date.
      • caps: recursion depth _EPO_SLICE_DEPTH_CAP, total probe calls
        _EPO_SLICE_PROBE_CAP. A leaf still > wall at the cap is marked
        truncated=True (caller may hand-split it); recursion stops there.
      • sum_check: Σ leaf totals vs parent total; drift > 5% →
        error_code=SLICE_INEFFECTIVE (date not honored / phantom slice).

    Returns {success, total, slices:[{date_from,date_to,total,truncated?}],
    sum_check:{sum,parent_total,ok}, probe_calls, provenance[], error_code?,
    message?}. EPO-only, no fallback; every failure is typed fail-fast.
    """
    if not epo_client.configured():
        return {
            "success": False, "error_code": "EPO_NOT_CONFIGURED",
            "message": "EPO slice_plan 需設 EPO_CONSUMER_KEY/SECRET",
            "provenance": [_entry("epo", "skipped", "not_configured")],
        }
    if not (spec.keyword or spec.ipc or spec.cpc or spec.uspc or spec.applicant):
        return {
            "success": False, "error_code": "INVALID_PARAMS",
            "message": "slice_plan 需至少一個檢索軸 (keyword/ipc/cpc/uspc/applicant)",
            "provenance": [],
        }

    prov: List[Dict[str, Any]] = []
    counter = {"probes": 0}

    async def _probe(df: Optional[str], dt: Optional[str]) -> int:
        counter["probes"] += 1
        return await _epo_probe_total(spec, epo_client, df, dt, prov)

    try:
        parent_total = await _probe(spec.date_from, spec.date_to)
    except BackendError as e:
        return {
            "success": False, "error_code": "EPO_ERROR",
            "message": str(e), "provenance": prov,
            "probe_calls": counter["probes"],
        }

    # ≤ wall → single slice (whatever date range the caller gave, or none).
    if parent_total <= _EPO_SKIP_WALL:
        slices = [{"date_from": spec.date_from, "date_to": spec.date_to,
                   "total": parent_total}]
        return {
            "success": True, "total": parent_total, "slices": slices,
            "sum_check": {"sum": parent_total, "parent_total": parent_total,
                          "ok": True},
            "probe_calls": counter["probes"], "provenance": prov,
        }

    # > wall but no date range → fail-fast, never guess a full-history span.
    if not (spec.date_from and spec.date_to):
        return {
            "success": False, "error_code": "DATE_RANGE_REQUIRED",
            "message": (f"total={parent_total} 超過 OPS skip wall "
                        f"({_EPO_SKIP_WALL}) 但缺 date 範圍;"
                        "請提供 date_from 且 date_to 以啟動 date 切片"),
            "total": parent_total, "provenance": prov,
            "probe_calls": counter["probes"],
        }

    # > wall with a date range → recursive bisection on mutually-exclusive cuts.
    leaves: List[Dict[str, Any]] = []

    async def _split(df: str, dt: str, total: int, depth: int) -> None:
        # leaf terminates when: under wall, OR depth/probe cap reached, OR the
        # window collapsed to a single day (can't bisect further).
        d_from = _parse_ymd(df)
        d_to = _parse_ymd(dt)
        if (total <= _EPO_SKIP_WALL or depth >= _EPO_SLICE_DEPTH_CAP
                or d_from >= d_to
                or counter["probes"] >= _EPO_SLICE_PROBE_CAP):
            leaf: Dict[str, Any] = {"date_from": df, "date_to": dt,
                                    "total": total}
            if total > _EPO_SKIP_WALL:
                leaf["truncated"] = True
            leaves.append(leaf)
            return
        # mutually-exclusive cut: left [df, mid], right [mid+1day, dt]
        mid = d_from + (d_to - d_from) // 2
        left_from, left_to = df, _fmt_ymd(mid)
        right_from, right_to = _fmt_ymd(mid + timedelta(days=1)), dt
        # budget guard: each half needs a probe; stop if the pair would blow cap.
        if counter["probes"] + 2 > _EPO_SLICE_PROBE_CAP:
            leaf = {"date_from": df, "date_to": dt, "total": total,
                    "truncated": True}
            leaves.append(leaf)
            return
        left_total = await _probe(left_from, left_to)
        right_total = await _probe(right_from, right_to)
        await _split(left_from, left_to, left_total, depth + 1)
        await _split(right_from, right_to, right_total, depth + 1)

    try:
        await _split(spec.date_from, spec.date_to, parent_total, 0)
    except BackendError as e:
        return {
            "success": False, "error_code": "EPO_ERROR",
            "message": str(e), "provenance": prov,
            "probe_calls": counter["probes"],
        }

    leaf_sum = sum(int(s["total"]) for s in leaves)
    drift_ok = (parent_total == 0) or (
        abs(leaf_sum - parent_total) <= _EPO_SLICE_SUM_TOL * parent_total)
    sum_check = {"sum": leaf_sum, "parent_total": parent_total, "ok": drift_ok}
    if not drift_ok:
        return {
            "success": False, "error_code": "SLICE_INEFFECTIVE",
            "message": (f"leaf-sum {leaf_sum} 與母數 {parent_total} 差異 "
                        f"> {int(_EPO_SLICE_SUM_TOL * 100)}%;date 切片在該 query "
                        "未生效(假切),拒交殘缺切片計畫"),
            "total": parent_total, "slices": leaves, "sum_check": sum_check,
            "probe_calls": counter["probes"], "provenance": prov,
        }
    return {
        "success": True, "total": parent_total, "slices": leaves,
        "sum_check": sum_check, "probe_calls": counter["probes"],
        "provenance": prov,
    }


async def bulk(
    spec: QuerySpec, source: str, *,
    gpss_client: Any, epo_client: Any, absorb_cb: Optional[Any] = None,
) -> Dict[str, Any]:
    """Unified bulk-harvest router (plans/patentmcp_bulk-entry-unification).

    `source` is REQUIRED and explicit — {"gpss", "epo"}. Anything else (or a
    missing value) is INVALID_PARAMS with ZERO backend calls: no implicit source
    default, no cross-source fallback (DD-1, the fail-fast天條).

    Routing (DD-2):
      • source="gpss" + no keyword → bulk_export (classification-axis full pull)
      • source="gpss" + keyword    → bulk_harvest (keyword収割)
      • source="epo"               → epo_bulk_harvest (absorb_cb passed through)

    The dispatcher-layer functions are reused UNCHANGED (DD-7); this router only
    dispatches and, for GPSS, back-fills the `next_skip`/`exhausted` continuation
    fields so the envelope is a superset uniform across both sources (DD-3). EPO
    already carries them from epo_bulk_harvest.
    """
    if source not in ("gpss", "epo"):
        return _envelope(
            False, [], None, [], [], None, error_code="INVALID_PARAMS",
            message="bulk 需顯式指定 source ('gpss' 或 'epo'),無預設值、無跨源 fallback",
        )
    if source == "epo":
        return await epo_bulk_harvest(spec, epo_client=epo_client, absorb_cb=absorb_cb)
    # source == "gpss": internal two-way by keyword presence (DD-2)
    if spec.keyword:
        env = await bulk_harvest(spec, gpss_client=gpss_client)
    else:
        env = await bulk_export(spec, gpss_client=gpss_client)
    # DD-3: back-fill EPO-style continuation fields at the ROUTER layer only
    # (bulk_export/bulk_harvest bodies untouched, DD-7). next_skip is the absolute
    # cursor after this page-set; exhausted when total is known and reached.
    if env.get("success"):
        total = env.get("total")
        next_skip = spec.skip + len(env.get("records") or [])
        env["next_skip"] = next_skip
        env["exhausted"] = bool(total is not None and next_skip >= total)
    return env


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
        # EPO out-of-jurisdiction guard: EPO's global index ignores the GPSS
        # `databases` filter, so when the caller scoped strictly to GPSS-only
        # jurisdictions (CN/TW), an EPO fallthrough returns wrong-jurisdiction
        # hits (a PL/EP case masquerading as a CN result) and a polluted total.
        # An honest zero_hits is correct here — never a silent cross-source rescue.
        if name == "epo" and spec.databases and all(
                str(d)[:2].upper() in _GPSS_ONLY_COUNTRIES for d in spec.databases):
            provenance.append(_entry(name, "skipped", "out_of_jurisdiction"))
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
