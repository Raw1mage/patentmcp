"""
Client for the Google Patents /xhr/query JSON endpoint.

This is the same backend the patents.google.com search UI calls. It returns
relevance-ranked results with bibliographic data, a representative-figure
thumbnail, and a link to the full PDF.
"""

import asyncio
import html as _html
import logging
import os
import random
import re
import time
import urllib.parse
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")


def _text(fragment: str) -> str:
    """Strip HTML tags and collapse whitespace, preserving newlines lightly."""
    s = _TAG_RE.sub(" ", fragment)
    s = _html.unescape(s)
    s = _WS_RE.sub(" ", s)
    return s.strip()


QUERY_URL = "https://patents.google.com/xhr/query"
PATENT_URL = "https://patents.google.com/patent/{pub}/en"
IMAGE_BASE = "https://patentimages.storage.googleapis.com/"
BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class GooglePatentsClient:
    """Async client for the unofficial Google Patents query endpoint."""

    def __init__(self, min_interval: Optional[float] = None, timeout: float = 30.0,
                 max_retries: Optional[int] = None):
        # The Google Patents xhr endpoint rate-limits bursts (HTTP 503). We:
        #   1. serialize every request (single-flight lock),
        #   2. space requests by min_interval seconds,
        #   3. on 503/429 back off exponentially and PARK a cooldown so the next
        #      requests (even different queries) wait it out rather than re-trip it.
        # Tunable via env so the cadence can be tightened without code changes.
        self.min_interval = float(
            os.getenv("PATENTS_GP_MIN_INTERVAL",
                      min_interval if min_interval is not None else 3.0))
        self.max_retries = int(
            os.getenv("PATENTS_GP_MAX_RETRIES",
                      max_retries if max_retries is not None else 4))
        self._lock = asyncio.Lock()
        self._last_req = 0.0       # monotonic time of last request
        self._cooldown_until = 0.0  # honor an active backoff window
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": BROWSER_UA, "Accept": "application/json"},
            follow_redirects=True,
        )

    async def _get(self, url: str) -> httpx.Response:
        """Single-flight, paced GET with 503/429 exponential backoff.

        Spacing and cooldown are enforced at the top of the loop, so a 503 parks
        a cooldown window that the retry — and any subsequent call — waits out.
        """
        async with self._lock:
            last_resp = None
            for attempt in range(self.max_retries + 1):
                now = time.monotonic()
                wait = max(self.min_interval - (now - self._last_req),
                           self._cooldown_until - now, 0.0)
                if wait > 0:
                    await asyncio.sleep(wait)
                try:
                    last_resp = await self._client.get(url)
                finally:
                    self._last_req = time.monotonic()
                if last_resp.status_code in (403, 429, 503):
                    backoff = 60.0
                    self._cooldown_until = time.monotonic() + backoff
                    logger.error(
                        "Google Patents %d (blocked/throttled). Fail-Fast active. Cooldown parked for %.0fs.",
                        last_resp.status_code, backoff)
                    last_resp.raise_for_status()
                return last_resp
            last_resp.raise_for_status()
            return last_resp

    @staticmethod
    def _build_inner(
        query: str,
        countries: Optional[List[str]],
        num: int,
        page: int,
        before: Optional[str],
        after: Optional[str],
        status: Optional[str],
        type_: Optional[str],
    ) -> str:
        # The endpoint takes a single url-encoded `url` param holding the real
        # query string (q=...&country=...&num=...&before=priority:YYYYMMDD ...).
        parts = [f"q={query}"]
        if countries:
            parts.append("country=" + ",".join(countries))
        if before:
            parts.append(f"before={before}")
        if after:
            parts.append(f"after={after}")
        if status:
            parts.append(f"status={status}")  # GRANT | APPLICATION
        if type_:
            parts.append(f"type={type_}")  # PATENT
        parts.append(f"num={num}")
        if page:
            parts.append(f"page={page}")
        return "&".join(parts)

    @staticmethod
    def _flatten(item: Dict[str, Any]) -> Dict[str, Any]:
        p = item.get("patent", {})
        thumb = p.get("thumbnail") or ""
        pdf = p.get("pdf") or ""
        country_status = (
            p.get("family_metadata", {})
            .get("aggregated", {})
            .get("country_status", [])
        )
        return {
            "rank": item.get("rank"),
            "publication_number": p.get("publication_number"),
            "title": (p.get("title") or "").strip(),
            "snippet": (p.get("snippet") or "").strip(),
            "priority_date": p.get("priority_date"),
            "filing_date": p.get("filing_date"),
            "publication_date": p.get("publication_date"),
            "grant_date": p.get("grant_date"),
            "inventor": p.get("inventor"),
            "assignee": p.get("assignee"),
            "language": p.get("language"),
            "representative_figure_url": (IMAGE_BASE + thumb) if thumb else None,
            # BR_20260628 E: this URL is a LOW-RES INDEX THUMBNAIL (~60x80 px),
            # NOT a report-grade figure. Flag the resolution level so callers /
            # skills never embed it in deliverables — use the PDF pipeline
            # (extract_representative_figure) for high-resolution figures.
            "representative_figure_resolution": "thumbnail" if thumb else None,
            "pdf_url": (IMAGE_BASE + pdf) if pdf else None,
            "num_figures": len(p.get("figures", []) or []),
            "family_country_status": country_status,
        }

    async def search(
        self,
        query: str,
        countries: Optional[List[str]] = None,
        num: int = 10,
        page: int = 0,
        before: Optional[str] = None,
        after: Optional[str] = None,
        status: Optional[str] = None,
        type_: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Relevance-ranked patent search via Google Patents.

        Args:
            query: free-text query (Google ranks semantically).
            countries: country codes to include; defaults to US/CN (priority
                jurisdictions). TW is low reference value and not default; pass
                it explicitly if needed.
            num: results per page (<=100).
            page: 0-based page index.
            before/after: date bounds like "priority:20200101" / "publication:20240101".
            status: "GRANT" or "APPLICATION".
            type_: "PATENT".
        """
        if countries is None:
            countries = ["US", "CN"]
        inner = self._build_inner(
            query, countries, num, page, before, after, status, type_
        )
        url = f"{QUERY_URL}?url={urllib.parse.quote(inner, safe='')}&exp="
        try:
            resp = await self._get(url)
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            logger.error(f"Google Patents search failed: {e}")
            return {"success": False, "error": str(e), "results": []}

        results = data.get("results", {})
        clusters = results.get("cluster", []) or []
        flat: List[Dict[str, Any]] = []
        for cl in clusters:
            for item in cl.get("result", []) or []:
                flat.append(self._flatten(item))
        return {
            "success": True,
            "total_num_results": results.get("total_num_results"),
            "total_num_pages": results.get("total_num_pages"),
            "page": page,
            "count": len(flat),
            "query": query,
            "countries": countries,
            "results": flat,
        }

    @staticmethod
    def _extract_abstract(html: str) -> str:
        m = re.search(r'<meta name="description" content="([^"]*)"', html)
        if m and m.group(1).strip():
            return _text(m.group(1))
        m = re.search(r'itemprop="abstract"[^>]*>(.*?)</section>', html, re.S)
        if m:
            return _text(m.group(1)).removeprefix("Abstract").strip()
        return ""

    @staticmethod
    def _extract_claims(html: str) -> List[Dict[str, Any]]:
        sec = re.search(r'itemprop="claims"[^>]*>(.*?)</section>', html, re.S)
        if not sec:
            return []
        content = sec.group(1)
        # Each claim is a top-level <div id="..." num="N" class="claim">. The id
        # scheme varies by office (US: CLM-00001, CN: en-cl0001), so anchor on the
        # full opening tag and capture num — this also keeps the body markup-clean.
        parts = re.split(r'<div\s+id="[^"]*"\s+num="(\d+)"\s+class="claim">', content)
        claims: List[Dict[str, Any]] = []
        for i in range(1, len(parts), 2):
            num = int(parts[i])
            body = parts[i + 1] if i + 1 < len(parts) else ""
            text = _text(body)
            if text:
                claims.append({"num": num, "text": text})
        return claims

    @staticmethod
    def _extract_description(html: str) -> str:
        m = re.search(r'itemprop="description"[^>]*>(.*?)</section>', html, re.S)
        return _text(m.group(1)) if m else ""

    @staticmethod
    def _extract_pdf_url(html: str) -> Optional[str]:
        """Extract citation_pdf_url from meta tags."""
        m = re.search(r'<meta\s+name="citation_pdf_url"\s+content="([^"]+)"', html)
        if m:
            url = m.group(1)
            # DD-3: Strict rejection of guessed paths
            if "/pdfs/" in url and len(url.split("/")[-1]) < 20:
                logger.warning(f"Rejected likely guessed PDF URL: {url}")
                return None
            return url
        return None

    async def resolve_pdf_url(self, publication_number: str) -> Dict[str, Any]:
        """Resolve the true hashed PDF URL for a known publication number."""
        url = PATENT_URL.format(pub=publication_number)
        try:
            resp = await self._get(url)
            html = resp.text
            pdf_url = self._extract_pdf_url(html)
            if pdf_url:
                return {"success": True, "publication_number": publication_number, "pdf_url": pdf_url}
            return {"success": False, "error": "NOT_FOUND", "message": "citation_pdf_url not found in page"}
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (429, 503):
                return {"success": False, "error": "THROTTLED", "http_code": e.response.status_code}
            return {"success": False, "error": "SERVICE_UNAVAILABLE", "http_code": e.response.status_code}
        except Exception as e:
            return {"success": False, "error": "FETCH_FAILURE", "message": str(e)}

    async def get_patent(
        self,
        publication_number: str,
        include_description: bool = False,
    ) -> Dict[str, Any]:
        """Fetch a patent's full abstract + claims from its Google Patents page.

        CN/JP/etc. pages are requested via /en, returning Google's English machine
        translation. When include_description is True the (large) description text
        is included in the result — callers should land it in the token store
        rather than return it through the model context.
        """
        url = PATENT_URL.format(pub=publication_number)
        try:
            resp = await self._get(url)
            html = resp.text
        except Exception as e:  # noqa: BLE001
            logger.error(f"Google Patents page fetch failed for {publication_number}: {e}")
            return {"success": False, "error": str(e), "publication_number": publication_number}

        abstract = self._extract_abstract(html)
        claims = self._extract_claims(html)
        out: Dict[str, Any] = {
            "success": True,
            "publication_number": publication_number,
            "abstract": abstract,
            "claims": claims,
            "claims_count": len(claims),
        }
        if include_description:
            out["description"] = self._extract_description(html)
        return out

    @staticmethod
    def fulltext_markdown(patent: Dict[str, Any]) -> str:
        """Assemble a patent dict (from get_patent include_description=True) into a
        markdown document for landing in the token store."""
        claims = patent.get("claims", [])
        return (
            f"# {patent.get('publication_number','')}\n\n## Abstract\n"
            f"{patent.get('abstract','')}\n\n## Claims\n"
            + "\n".join(f"{c['num']}. {c['text']}" for c in claims)
            + f"\n\n## Description\n{patent.get('description','')}\n"
        )

    async def fetch_bytes(self, url: str) -> bytes:
        """Fetch raw bytes from a patentimages URL (PDF/figure). Raises on error."""
        resp = await self._get(url)
        return resp.content

    async def close(self):
        await self._client.aclose()
