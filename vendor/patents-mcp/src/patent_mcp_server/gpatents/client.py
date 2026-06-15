"""
Client for the Google Patents /xhr/query JSON endpoint.

This is the same backend the patents.google.com search UI calls. It returns
relevance-ranked results with bibliographic data, a representative-figure
thumbnail, and a link to the full PDF.
"""

import asyncio
import html as _html
import logging
import re
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

    def __init__(self, min_interval: float = 1.0, timeout: float = 30.0):
        # Be polite to the unofficial endpoint: serialize + space out requests.
        self.min_interval = min_interval
        self._lock = asyncio.Lock()
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": BROWSER_UA, "Accept": "application/json"},
            follow_redirects=True,
        )

    async def _get(self, url: str) -> httpx.Response:
        # Single-flight + min-interval throttle so we never burst the endpoint.
        async with self._lock:
            resp = await self._client.get(url)
            await asyncio.sleep(self.min_interval)
        resp.raise_for_status()
        return resp

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
