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
import json
import logging
import os
import re
import urllib.parse
from typing import Any, Dict, List, Optional

import httpx

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


class GPSSClient:
    """Async client for the TIPO GPSS REST API."""

    def __init__(self, user_code: Optional[str] = None, timeout: float = 40.0):
        self.user_code = user_code or os.getenv("GPSS_USER_CODE")
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

    def configured(self) -> bool:
        return bool(self.user_code)

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
        is required by the API). Returns parsed JSON (or raw text if XML)."""
        if not self.user_code:
            return {
                "success": False,
                "error": "GPSS_USER_CODE not set. Apply for a userCode at TIPO and "
                "set the GPSS_USER_CODE environment variable.",
            }
        if not conditions:
            return {"success": False, "error": "At least one search condition is required."}

        if databases is None:
            databases = DB_DEFAULT
        params = [("userCode", self.user_code)] + self._build_query(
            conditions, databases, case_type, patent_type, fields, fmt, num, skip
        )
        # GPSS field names contain '/' (TI/AB) and the +/- combinators ride in the
        # KEY; httpx's param encoder would percent-encode those and break the query.
        # Build the query string by hand: keys literal, values url-encoded.
        qs = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params)
        url = f"{GPSS_API_URL}?{qs}"
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
        except Exception as e:  # noqa: BLE001
            logger.error(f"GPSS request failed: {e}")
            return {"success": False, "error": str(e)}

        text = resp.text
        if fmt == "json":
            data = _parse_gpss_json(text)
            if data is None:
                logger.error(
                    "GPSS JSON unrecoverable after control-char + illegal-escape "
                    "sanitize (len=%d, skip=%s)", len(text), skip,
                )
                return {"success": False, "error": "Expected JSON but parse failed", "raw": text[:500]}
            
            if not isinstance(data, dict):
                return {"success": False, "error": f"Expected JSON object but got {type(data).__name__}", "raw": text[:500]}
            
            api = data.get("gpss-API") or data
            if not isinstance(api, dict):
                return {"success": False, "error": f"Expected JSON object inside gpss-API but got {type(api).__name__}", "raw": text[:500]}
                
            status = api.get("status")
            message = api.get("message")
            # status=success with a message means "no record found" / error string.
            return {
                "success": status == "success" and not message,
                "status": status,
                "message": message,
                "total": api.get("total-rec"),
                "qty": api.get("qty-rec"),
                "data": data,
            }
        return {"success": True, "format": "xml", "raw": text}

    async def close(self):
        await self._client.aclose()
