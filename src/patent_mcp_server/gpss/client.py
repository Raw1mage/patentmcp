"""
Client for the TIPO GPSS patent-search REST API.

API shape (from TIPO "GPSS API 服務說明文件" v1.4):
    GET https://tiponet.tipo.gov.tw/gpss1/gpsskmc/gpss_api?userCode=<code>&<field>=<value>&...

- Every parameter is &-joined. Within a field, keywords combine with and/or/not.
- Across fields the default is AND; prefix a field with '+' for OR, '-' for NOT.
- Output is XML by default; pass expFmt=json for JSON.

Auth: a single userCode (API 驗證碼) issued by TIPO after approval.
"""

import json
import logging
import os
import re
import urllib.parse
from typing import Any, Dict, List, Optional

import httpx

from patent_mcp_server.gpss.quota_state import QuotaStateStore

logger = logging.getLogger(__name__)

GPSS_API_URL = "https://tiponet.tipo.gov.tw/gpss1/gpsskmc/gpss_api"

# GPSS emits JSON whose patent text fields (TI/AB/CL) occasionally contain a
# LITERAL backslash that GPSS failed to escape — e.g. a claim reading
# "毫米波\太赫兹" uses '\' as a '/' separator. In JSON a backslash must be
# followed by one of " \ / b f n r t u; '\太' is an *illegal escape* that
# BOTH json.loads(strict=True) AND json.loads(strict=False) reject (strict=False
# only tolerates raw control chars, not illegal escapes). This only surfaces on
# pages that carry full-text fields (a PN-only query never trips it), which is
# why deep bulk-harvest pages fail while a light patent_search of the same skip
# succeeds. Sanitize by doubling any backslash that is NOT a valid JSON escape
# introducer, then re-parse. Verified: recovers a 1.3MB body (7 stray '\' → 200
# records) that both strict modes rejected.
_ILLEGAL_JSON_ESCAPE = re.compile(r'\\(?!["\\/bfnrtu])')

# BR_20260718: an unrecoverable parse in the RESIDENT process is almost always a
# TRUNCATED body from a Cloudflare-killed keep-alive connection, not a formatting
# malformation (those are handled by _parse_gpss_json's 3 layers). Disabling
# keep-alive (limits below) reduced but did not eliminate it, so on parse
# failure we retry the SAME url on a fresh ONE-SHOT client (short-lived clients
# never reproduce the truncation) before failing loud with a TRANSPORT-semantics
# error code that downstream must never read as zero hits.
_TRUNCATION_RETRIES = 2


def _parse_gpss_json(text: str) -> Optional[Dict[str, Any]]:
    """Parse a GPSS JSON body, tolerating GPSS's two known malformations.

    Returns the parsed dict, or None if unrecoverable. Single source of truth:
    every caller (patent_search / bulk_harvest / bulk_export) parses here.
    """
    # 1) strict — the common, clean case.
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        pass
    # 2) strict=False — tolerate raw control characters inside string values.
    try:
        return json.loads(text, strict=False)
    except Exception:  # noqa: BLE001
        pass
    # 3) sanitize illegal backslash escapes, then re-parse (still strict=False
    #    so a co-occurring control char doesn't re-break it).
    try:
        return json.loads(_ILLEGAL_JSON_ESCAPE.sub(r'\\\\', text), strict=False)
    except Exception:  # noqa: BLE001
        return None

# Database codes (patDB). Priority jurisdictions are US/CN; TW is low value.
DB_US = ["USA", "USB"]   # US 公開 / 公告
DB_CN = ["CNA", "CNB"]   # CN 公開 / 公告
DB_DEFAULT = DB_US + DB_CN

# Sensible default output fields (PN/ID/title/inventor/applicant/abstract/CPC/claims).
DEFAULT_FIELDS = "PN,ID,TI,IN,PA,AB,CS,CL"


class GPSSCondition:
    """One search condition. op is the cross-field combinator with the PREVIOUS
    condition: 'AND' (default, no prefix), 'OR' ('+'), 'NOT' ('-')."""

    def __init__(self, field: str, value: str, op: str = "AND"):
        self.field = field
        self.value = value
        self.op = op.upper()

    def as_param(self, first: bool) -> str:
        prefix = ""
        if not first:
            prefix = {"AND": "", "OR": "+", "NOT": "-"}.get(self.op, "")
        return f"{prefix}{self.field}={self.value}"


# TIPO GPSS time-window quota-exhausted signal. GPSS bills by OUTPUT record
# count and resets per time-window (weekday 08-18 narrow 10,000 / off-hours +
# weekend wide 30,000). When a userCode's window quota is spent, GPSS returns
# status=success but a message containing "Over download quantity". We rotate to
# the next account ONLY on this signal — a "no record found" message is NOT
# exhaustion and must not trigger rotation (would burn all accounts). Matched
# case-insensitively as a substring. "Over search quantity" is the alternate
# phrasing of the same time-window output cap.
_QUOTA_EXHAUSTED_MARKERS = ("over download quantity", "over search quantity")


def _is_quota_exhausted(message: Optional[str]) -> bool:
    """True IFF the GPSS message is a time-window quota-exhausted signal (DD-2).

    Strictly distinct from "no record found": only the official over-quantity
    markers count, so a normal empty-result message never triggers rotation.
    """
    if not message:
        return False
    low = message.lower()
    return any(marker in low for marker in _QUOTA_EXHAUSTED_MARKERS)


def _load_user_codes(explicit: Optional[List[str]]) -> List[str]:
    """Resolve the account pool (DD-4).

    Priority: explicit constructor arg > GPSS_USER_CODES (comma-separated) >
    GPSS_USER_CODE (legacy single code). Strips whitespace, drops empties,
    de-duplicates while preserving order.
    """
    raw: List[str]
    if explicit is not None:
        raw = list(explicit)
    else:
        codes_env = os.getenv("GPSS_USER_CODES")
        if codes_env and codes_env.strip():
            raw = codes_env.split(",")
        else:
            single = os.getenv("GPSS_USER_CODE")
            raw = [single] if single else []
    seen: set = set()
    out: List[str] = []
    for c in raw:
        if c is None:
            continue
        code = c.strip()
        if code and code not in seen:
            seen.add(code)
            out.append(code)
    return out


class GPSSClient:
    """Async client for the TIPO GPSS REST API.

    Holds an ORDERED POOL of userCode accounts and rotates through them when a
    time-window quota is exhausted (DD-1..DD-8). Rotation is internal to
    search() so every caller sharing the module-level instance benefits
    transparently.

    Exhausted-account state is keyed by (account_code, window_key) and persisted
    in a cross-process sqlite sidecar (owning plan DD-7/DD-8, BR_20260718),
    superseding the old process-local cursor-index set (DD-3):

    - **Implicit revival**: crossing a GPSS quota-reset boundary changes
      window_key, so an account exhausted in an earlier window is automatically
      considered live again — no restart needed (the resident MCP process never
      restarts, so the old "a restart clears it" assumption was broken).
    - **Cross-process sharing**: parallel subagent processes share one sidecar,
      so an account one process marks exhausted is immediately skipped by the
      others (roots out the DD-97 stampede).
    """

    def __init__(
        self,
        user_code: Optional[str] = None,
        user_codes: Optional[List[str]] = None,
        timeout: float = 40.0,
        quota_store: Optional[QuotaStateStore] = None,
    ):
        # Back-compat: a single positional user_code seeds a 1-account pool.
        explicit: Optional[List[str]] = None
        if user_codes is not None:
            explicit = list(user_codes)
        elif user_code is not None:
            explicit = [user_code]
        self.user_codes: List[str] = _load_user_codes(explicit)
        self._cursor: int = 0
        # Cross-process, window-keyed exhausted-state store (DD-7/DD-8). Kept
        # injectable so tests can pass an isolated on-disk sidecar.
        self._quota_store: QuotaStateStore = quota_store or QuotaStateStore()
        # GPSS sits behind Cloudflare (resp headers carry cf-ray). In a
        # long-lived MCP-server process the single client's pool holds
        # keep-alive connections that Cloudflare silently drops after an idle
        # window; reusing such a half-dead connection on a deep-pagination page
        # returns a truncated/malformed body -> resp.json() parse failed. Only
        # the resident process reproduces it (a fresh short-lived client / curl
        # never does). Disable keep-alive reuse so every request opens a fresh
        # connection. GPSS pagination is stateless (no Set-Cookie), so nothing
        # is lost by not reusing the connection.
        self._client = httpx.AsyncClient(
            timeout=timeout, follow_redirects=True,
            limits=httpx.Limits(max_keepalive_connections=0),
        )

    def _is_idx_exhausted(self, idx: int) -> bool:
        """True IFF the account at cursor `idx` is on record as exhausted for the
        CURRENT window (DD-7). Records from an older window_key don't match, so
        an account revives implicitly once the window rolls over."""
        if idx < 0 or idx >= len(self.user_codes):
            return True
        return self._quota_store.is_exhausted(self.user_codes[idx])

    def _seek_live_cursor(self) -> bool:
        """Move the cursor to the first account not exhausted in the current
        window. Returns True if a live account exists, False if the whole pool
        is exhausted this window (DD-5/DD-7/DD-8)."""
        if self.user_codes and not self._is_idx_exhausted(self._cursor):
            return True
        for idx in range(len(self.user_codes)):
            if not self._is_idx_exhausted(idx):
                self._cursor = idx
                return True
        return False

    @property
    def user_code(self) -> Optional[str]:
        """The current-cursor userCode (back-compat: external refs still read this).

        Returns None when the pool is empty OR every account is exhausted in the
        current window. Reflects the account search() will use next.
        """
        if not self.user_codes:
            return None
        if self._seek_live_cursor():
            return self.user_codes[self._cursor]
        return None

    def _advance_account(self) -> bool:
        """Mark the current account exhausted (in the sidecar, keyed by the
        current window) and move the cursor to the next account not exhausted
        this window. Returns True if such an account exists, False if the whole
        pool is now exhausted (DD-5/DD-7/DD-8)."""
        if 0 <= self._cursor < len(self.user_codes):
            self._quota_store.mark_exhausted(self.user_codes[self._cursor])
        for idx in range(len(self.user_codes)):
            if not self._is_idx_exhausted(idx):
                self._cursor = idx
                return True
        return False

    def configured(self) -> bool:
        return bool(self.user_codes)

    async def _fresh_get(self, url: str) -> httpx.Response:
        """GET `url` on a brand-new one-shot client (BR_20260718 truncation
        retry). A short-lived client never reproduces the Cloudflare half-dead
        keep-alive truncation; factored out so tests can fake it."""
        async with httpx.AsyncClient(
            timeout=self._client.timeout, follow_redirects=True,
        ) as one:
            resp = await one.get(url)
            resp.raise_for_status()
            return resp

    @staticmethod
    def _build_query(
        conditions: List[GPSSCondition],
        databases: Optional[List[str]],
        case_type: Optional[str],
        patent_type: Optional[str],
        fields: str,
        fmt: str,
        num: int,
        skip: int,
    ) -> List[str]:
        # Note: GPSS expects the raw query syntax; values may contain spaces and
        # and/or/not. httpx will percent-encode params when passed via `params`,
        # so we return (key, value) pairs and let httpx encode. But '+'/'-' field
        # prefixes are part of the KEY, so they ride along in the key.
        params: List[tuple] = []
        if databases:
            params.append(("patDB", ",".join(databases)))
        if case_type:
            params.append(("patAG", case_type))
        if patent_type:
            params.append(("patTY", patent_type))
        for i, c in enumerate(conditions):
            prefix = ""
            if i > 0:
                prefix = {"AND": "", "OR": "+", "NOT": "-"}.get(c.op, "")
            params.append((f"{prefix}{c.field}", c.value))
        params.append(("expFld", fields))
        params.append(("expFmt", fmt))
        params.append(("expQty", str(num)))
        if skip:
            params.append(("expSkip", str(skip)))
        return params

    async def search(
        self,
        conditions: List[GPSSCondition],
        databases: Optional[List[str]] = None,
        case_type: Optional[str] = None,
        patent_type: Optional[str] = None,
        fields: str = DEFAULT_FIELDS,
        num: int = 30,
        skip: int = 0,
        fmt: str = "json",
    ) -> Dict[str, Any]:
        """Run a GPSS search. `conditions` is a list of GPSSCondition (at least one
        is required by the API). Returns parsed JSON (or raw text if XML).

        Rotates through the userCode account pool: if the current account's
        time-window quota is exhausted (GPSS message "Over download quantity"),
        the request is retried on the next not-yet-exhausted account. When the
        whole pool is exhausted, returns GPSS_ALL_ACCOUNTS_EXHAUSTED fail-fast
        (DD-1..DD-6).
        """
        if not self.configured():
            return {
                "success": False,
                "error": "GPSS_USER_CODE not set. Apply for a userCode at TIPO and "
                "set the GPSS_USER_CODES (or legacy GPSS_USER_CODE) environment variable.",
            }
        if not conditions:
            return {"success": False, "error": "At least one search condition is required."}

        if databases is None:
            databases = DB_DEFAULT

        # Rotation loop: at most one attempt per not-yet-exhausted account.
        # Bound by the pool size so a pool of all-exhausted accounts can never
        # loop forever.
        accounts_tried = 0
        while True:
            if self.user_code is None:
                # No live account left in the pool.
                return {
                    "success": False,
                    "error_code": "GPSS_ALL_ACCOUNTS_EXHAUSTED",
                    "error": (
                        f"All {len(self.user_codes)} GPSS account(s) have exhausted "
                        "their time-window quota. Retry later (GPSS quota resets per "
                        "time-window; off-hours/weekend has the wider cap) or add more "
                        "accounts to GPSS_USER_CODES."
                    ),
                    "accounts_tried": accounts_tried,
                }

            current_code = self.user_code
            accounts_tried += 1
            params = [("userCode", current_code)] + self._build_query(
                conditions, databases, case_type, patent_type, fields, fmt, num, skip
            )
            # GPSS field names contain '/' (TI/AB) and the +/- combinators ride in
            # the KEY; httpx's param encoder would percent-encode those and break
            # the query. Build the query string by hand: keys literal, values
            # url-encoded.
            qs = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params)
            url = f"{GPSS_API_URL}?{qs}"
            try:
                resp = await self._client.get(url)
                resp.raise_for_status()
            except Exception as e:  # noqa: BLE001
                logger.error(f"GPSS request failed: {e}")
                # Transport/HTTP errors are not quota exhaustion (DD-6) — return
                # as-is without rotating.
                return {"success": False, "error": str(e)}

            text = resp.text
            if fmt != "json":
                return {"success": True, "format": "xml", "raw": text}

            data = _parse_gpss_json(text)
            # BR_20260718: parse failure here = suspected TRUNCATED body (see
            # _TRUNCATION_RETRIES note). Retry on fresh one-shot connections
            # before failing loud with transport semantics.
            if data is None:
                for attempt in range(1, _TRUNCATION_RETRIES + 1):
                    logger.warning(
                        "GPSS body unparseable (len=%d, skip=%s) — suspected "
                        "truncated keep-alive body; fresh-connection retry %d/%d",
                        len(text), skip, attempt, _TRUNCATION_RETRIES,
                    )
                    try:
                        r2 = await self._fresh_get(url)
                    except Exception as e:  # noqa: BLE001
                        logger.error(f"GPSS truncation-retry request failed: {e}")
                        continue
                    text = r2.text
                    data = _parse_gpss_json(text)
                    if data is not None:
                        break
            if data is None:
                logger.error(
                    "GPSS JSON unrecoverable after sanitize + %d fresh-connection "
                    "retries (len=%d, skip=%s)", _TRUNCATION_RETRIES, len(text), skip,
                )
                return {
                    "success": False,
                    "error_code": "GPSS_TRUNCATED_BODY",
                    "error": (
                        "GPSS returned an unparseable (likely truncated) JSON body "
                        f"after {_TRUNCATION_RETRIES} fresh-connection retries. "
                        "TRANSPORT failure, NOT an empty result — never interpret "
                        "as zero hits / missing recall capability."
                    ),
                    "transport": "truncation",
                    "raw": text[:500],
                }

            if not isinstance(data, dict):
                return {"success": False, "error": f"Expected JSON object but got {type(data).__name__}", "raw": text[:500]}

            api = data.get("gpss-API") or data
            if not isinstance(api, dict):
                return {"success": False, "error": f"Expected JSON object inside gpss-API but got {type(api).__name__}", "raw": text[:500]}

            status = api.get("status")
            message = api.get("message")

            # Time-window quota exhausted (DD-2): rotate to the next account and
            # retry the SAME request. Strictly distinct from "no record found".
            if _is_quota_exhausted(message):
                logger.warning(
                    "GPSS account #%d quota exhausted (%r), rotating to next",
                    self._cursor, message,
                )
                if self._advance_account():
                    continue
                # Pool now fully exhausted — loop head returns the fail-fast.
                continue

            # status=success with a message means "no record found" / error string.
            return {
                "success": status == "success" and not message,
                "status": status,
                "message": message,
                "total": api.get("total-rec"),
                "qty": api.get("qty-rec"),
                "data": data,
            }

    async def close(self):
        await self._client.aclose()
