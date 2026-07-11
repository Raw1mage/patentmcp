"""
USPTO Patent Search MCP Server

This file provides a Model Context Protocol (MCP) server that exposes tools for interacting with multiple USPTO APIs:

1. ppubs.uspto.gov - Provides full text patent documents, PDF downloads, and advanced search
2. api.uspto.gov - Provides metadata, continuity information, transactions, and assignments

The server uses stdio transport for command-line tools, following the MCP standard.
"""
import asyncio
import contextlib
import os
import json
import logging
import random
import sys
from typing import Any, Dict, List, Optional, Union

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

# Initialize FastMCP server. The instructions reach every client (stdio + http)
# via InitializeResult — they point at the companion patentworks skill so the
# MCP and skill wake each other (skill <-> tools cross-reference).
mcp = FastMCP(
    "patentmcp",
    instructions=(
        "Patent-data tools: USPTO / Google Patents / GPSS / EPO. "
        "Before any patent search or drafting task, load the companion "
        "**patentworks** skill — it is the playbook for these tools "
        "(disclosure -> screening -> drafting) and carries the per-jurisdiction "
        "drafting rules that decide which tool to call and what to deliver. "
        "Patent SEARCH goes through the single patent_search tool — the "
        "source ladder (GPSS > EPO > PPUBS > gated Google Patents scraping) "
        "is built into the server; do not pick sources yourself. Scraping "
        "requires allow_scraping=True with explicit user authorization. "
        "Tool results return file handles; "
        "bytes are delivered via /files/{token}/blob/{rel}, not through context. "
        "USAGE GUIDE: this service self-ships its full usage doctrine — call "
        "patentmcp_init (or prompts/get patentmcp_init) for organ-coordination, "
        "cross-tool tradeoffs, pre-call disciplines, and gotchas before first use."
    ),
)

# Read-only annotation for query-class tools. Clients (e.g. opencode's batch
# tool) admit readOnlyHint=true MCP tools into batched execution — sequential,
# payload order, never parallel — so several lookups cost one turn without
# fanning out against source-API rate limits. patent_search qualifies: its
# patentdb absorb is an idempotent internal cache write, semantically still a
# query (user ruling 2026-07-06).
_RO = ToolAnnotations(readOnlyHint=True)

# ---------------------------------------------------------------------
# R15 self-describing guide — one-source doctrine loader.
# /plans/mcp_r15-self-describing-guide DD-1/DD-2/DD-3.
#
# The patentworks companion skill SKILL.md IS the single authoritative
# usage doctrine (cross-tool tradeoffs / source ladder / pre-call
# disciplines / organ coordination / gotchas). The patentmcp_init TOOL
# and the prompts/get patentmcp_init entry both project THIS file, so
# all three faces stay byte-identical (R15.5 no-drift). Loaded once at
# first access and cached; missing/empty source fails fast (天條 11 —
# a guide with no doctrine is byte-identical to no contract).
# ---------------------------------------------------------------------
from pathlib import Path as _Path


def _skills_root() -> _Path:
    """Repo ``skills/`` dir (mirrors _http_app._skills_root). Override with
    PATENTS_SKILLS_ROOT; else derive from this file's location (repo root is
    parents[4] of …/src/patent_mcp_server/patents.py)."""
    env = os.environ.get("PATENTS_SKILLS_ROOT")
    if env:
        return _Path(env)
    return _Path(__file__).resolve().parents[4] / "skills"


_DOCTRINE_PATH = _skills_root() / "patentworks" / "SKILL.md"


def _guide_doctrine() -> str:
    """Return the patentmcp R15 usage doctrine (patentworks SKILL.md).

    Fail-fast on missing/empty source — never serve an empty guide (天條 11).
    Read per-request (NOT cached): the doctrine is a few-KB markdown file read
    only on the cold `patentmcp_init` / prompts/get path, never a hot loop, so
    a fresh read costs nothing and lets a bind-mounted doctrine edit take effect
    with zero image rebuild (R15 live-reload). Same file read by tool +
    prompts/get faces so both stay byte-identical (R15.5 no-drift)."""
    try:
        text = _DOCTRINE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"DOCTRINE_SOURCE_MISSING: patentmcp usage doctrine not found at "
            f"{_DOCTRINE_PATH}; the patentmcp_init surface cannot serve an "
            f"empty contract (天條 11). Confirm Dockerfile COPY skills/ and "
            f"PATENTS_SKILLS_ROOT."
        ) from exc
    if not text.strip():
        raise RuntimeError(
            f"DOCTRINE_SOURCE_EMPTY: patentmcp usage doctrine at "
            f"{_DOCTRINE_PATH} is empty/whitespace; refusing to serve an "
            f"empty guide (天條 11)."
        )
    return text


# Set up logging
logging.basicConfig(
    level=logging.INFO, # for production
    #level=logging.DEBUG, # for debugging
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger('uspto_patent_mcp')

# Import USPTO client implementations
from patent_mcp_server.uspto.ppubs_uspto_gov import PpubsClient
from patent_mcp_server.uspto.api_uspto_gov import ApiUsptoClient
from patent_mcp_server.google.bigquery_client import GoogleBigQueryClient, BudgetExceededError
from patent_mcp_server.gpatents.client import GooglePatentsClient
from patent_mcp_server.gpss.client import GPSSClient, GPSSCondition
from patent_mcp_server.epo.client import EPOClient
from patent_mcp_server._token_store import default_store
from patent_mcp_server import _file_server
from patent_mcp_server import screening_table as _st
from patent_mcp_server import search_audit as _sa
from patent_mcp_server import search_dispatcher as _sd
from patent_mcp_server import patentdb_store as _pdb
from patent_mcp_server.constants import Defaults, GooglePatentsCountries
from patent_mcp_server.util.errors import ApiError

# Constants
USPTO_API_BASE = "https://api.uspto.gov"

# Create client instances for each USPTO API
ppubs_client = PpubsClient()  # ppubs.uspto.gov module
api_client = ApiUsptoClient() # api.uspto.gov module
google_bq_client = GoogleBigQueryClient()  # Google Patents BigQuery module
gpatents_client = GooglePatentsClient()  # Google Patents web endpoint (ranked search + figures + PDF)
gpss_client = GPSSClient()  # TIPO GPSS official REST API (CPC/IPC + claims search, US/CN, JSON)
epo_client = EPOClient()  # EPO OPS official API (INPADOC family, citations, biblio, legal)
token_store = default_store()  # docxmcp-compatible token store for file delivery

# ---------------------------------------------------------------------
# GPSS scraping single-thread guardrail (BR_20260628 A).
# TIPO (tiponet.tipo.gov.tw) is fronted by Cloudflare. Parallel scraping
# trips a Managed Challenge that silently hangs the connection. Every
# self-built GPSS scraping tool (figure / pdf / xml) MUST serialize through
# the per-host SoftScrapePolicy (Concurrency=1 + random pacing + cooldown
# parking). Single-process async server -> asyncio.Lock is sufficient.
#
# plan gpss-session-reuse-batch (extend): the ad-hoc lock+pace pair is now a
# unified SoftScrapePolicy shared with the other crawler surface (USPTO ppubs).
# Backward-compat aliases (_GPSS_SCRAPE_LOCK / _gpss_scrape_pace / MIN/MAX) are
# kept so existing call sites + tests keep working unchanged.
from patent_mcp_server.util.soft_scrape import SoftScrapePolicy

_GPSS_SCRAPE_MIN_DELAY = float(os.getenv("GPSS_SCRAPE_MIN_DELAY", "1.0"))
_GPSS_SCRAPE_MAX_DELAY = float(os.getenv("GPSS_SCRAPE_MAX_DELAY", "3.0"))
_GPSS_SCRAPE_COOLDOWN_S = float(os.getenv("GPSS_SCRAPE_COOLDOWN_S", "60.0"))

_GPSS_POLICY = SoftScrapePolicy(
    name="TIPO-GPSS",
    min_delay=_GPSS_SCRAPE_MIN_DELAY,
    max_delay=_GPSS_SCRAPE_MAX_DELAY,
    cooldown_default_s=_GPSS_SCRAPE_COOLDOWN_S,
)

# Backward-compat aliases — the policy IS the single source of truth now.
_GPSS_SCRAPE_LOCK = _GPSS_POLICY.lock


async def _gpss_scrape_pace() -> None:
    """Random inter-request delay (delegates to _GPSS_POLICY.delay).

    Kept as a thin alias so existing call sites + tests keep working. Callers
    must already hold _GPSS_POLICY.lock (via .guard() or the alias lock)."""
    await _GPSS_POLICY.delay()


# Browser-like headers shared by every GPSS scrape (figure / pdf / xml). Hoisted
# to module level so the single-call path and the reusable session use the SAME
# fingerprint — important for Cloudflare cf_clearance continuity.
_GPSS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}


@contextlib.asynccontextmanager
async def _gpss_client(injected):
    """Yield an httpx client for a GPSS scrape burst.

    - injected is not None -> REUSE it (a persistent session client); the caller
      owns its lifecycle, so we do NOT close it here. This is what lets a batch
      keep ONE cookie jar / cf_clearance across many sequential scrapes.
    - injected is None -> create a throwaway client and close it on exit (the
      original single-call behaviour, unchanged).
    """
    import httpx
    if injected is not None:
        yield injected
    else:
        async with httpx.AsyncClient(
            headers=_GPSS_HEADERS, follow_redirects=True, timeout=20.0
        ) as c:
            yield c


class _GpssScrapeSession:
    """A reusable single-thread GPSS scrape session for one batch.

    Holds ONE persistent httpx.AsyncClient whose cookie jar accumulates across
    every fetch — so the portal/GPSS handshake's Cloudflare cf_clearance cookie
    is reused instead of being discarded per patent (the deeper RCA of the
    ReadTimeout: a fresh client per request looks like a brand-new suspicious
    client to Cloudflare and is MORE likely to trip the Managed Challenge).

    Concurrency=1 is preserved: each fetch acquires _GPSS_SCRAPE_LOCK and paces
    BEFORE its HTTP burst, then releases. The lock is per-burst (not held across
    the whole batch loop), so a non-TW item routing through
    extract_representative_figure -> fetch_patent_pdf -> gpss_pdf cannot deadlock
    on the non-reentrant asyncio.Lock.
    """

    def __init__(self):
        import httpx
        self._client = httpx.AsyncClient(
            headers=_GPSS_HEADERS, follow_redirects=True, timeout=20.0
        )

    async def fetch_representative_figure(self, publication_number: str) -> Dict[str, Any]:
        async with _GPSS_POLICY.guard():
            return await _gpss_download_representative_figure_impl(
                publication_number, session_client=self._client
            )

    async def fetch_pdf(self, publication_number: str) -> Dict[str, Any]:
        async with _GPSS_POLICY.guard():
            return await _gpss_download_patent_pdf_impl(
                publication_number, session_client=self._client
            )

    async def fetch_xml(self, publication_number: str) -> Dict[str, Any]:
        async with _GPSS_POLICY.guard():
            return await _gpss_download_patent_xml_impl(
                publication_number, session_client=self._client
            )

    async def close(self) -> None:
        try:
            await self._client.aclose()
        except Exception as e:  # noqa: BLE001
            logger.warning("GPSS scrape session close failed: %s", e)

# =====================================================================
# Unified USPTO Patents Tool
# =====================================================================

async def _ppubs_resolve_patent_by_number(patent_number: Union[str, int]) -> Dict[str, Any]:
    """Resolve a PPUBS patent hit (guid + type) from a patent/publication number.

    Reuses the patentNumber query + ".pn." alternative-query lookup shared by
    ppubs_get_patent_by_number / ppubs_get_full_document. Returns the matched
    patent dict (with at least "guid" and "type"), or {"error": True, ...} when
    the upstream query errored or no patent matched.
    """
    patent_number = str(patent_number)

    search_query = f'patentNumber:"{patent_number}"'
    logger.info(f"Searching for patent with query: {search_query}")
    result = await ppubs_client.run_query(query=search_query, sources=["USPAT"], limit=1)
    if result.get("error", False):
        return result

    if result.get("patents") and len(result["patents"]) > 0:
        patent = result["patents"][0]
        logger.info(f"Found patent: {patent.get('guid')}")
        return patent
    if result.get("docs") and len(result["docs"]) > 0:
        patent = result["docs"][0]
        logger.info(f"Found patent: {patent.get('guid')}")
        return patent

    # Alternative query format
    alternative_query = f'"{patent_number}".pn.'
    logger.info(f"No results found, trying alternative query: {alternative_query}")
    result = await ppubs_client.run_query(query=alternative_query, sources=["USPAT"], limit=1)
    if result.get("error", False):
        return result

    if result.get("patents") and len(result["patents"]) > 0:
        return result["patents"][0]
    if result.get("docs") and len(result["docs"]) > 0:
        return result["docs"][0]
    return {"error": True, "message": f"Patent {patent_number} not found"}


@mcp.tool()
async def uspto_patents(
    method: str,
    # Search parameters (for ppubs_search_patents and ppubs_search_applications)
    query: Optional[str] = None,
    start: Optional[int] = 0,
    limit: Optional[int] = 100,
    sort: Optional[str] = "date_publ desc",
    default_operator: Optional[str] = "OR",
    expand_plurals: Optional[bool] = True,
    british_equivalents: Optional[bool] = True,
    # Document retrieval parameters (for ppubs_get_full_document)
    guid: Optional[str] = None,
    source_type: Optional[str] = None,
    # Patent number parameters (for ppubs_get_patent_by_number and ppubs_download_patent_pdf)
    patent_number: Optional[Union[str, int]] = None,
    # Publication number convenience param (for ppubs_get_full_document without a guid)
    publication_number: Optional[Union[str, int]] = None,
    # Application number parameter (for all get_app_* methods)
    app_num: Optional[str] = None,
    # Search applications parameters (for search_applications and download_applications)
    q: Optional[str] = None,
    offset: Optional[int] = 0,
    facets: Optional[str] = None,
    fields: Optional[str] = None,
    filters: Optional[str] = None,
    range_filters: Optional[str] = None,
    format: Optional[str] = "json",
    # POST search parameters (for search_applications_post and download_applications_post)
    filters_list: Optional[List[Dict[str, Any]]] = None,
    range_filters_list: Optional[List[Dict[str, Any]]] = None,
    sort_list: Optional[List[Dict[str, Any]]] = None,
    fields_list: Optional[List[str]] = None,
    facets_list: Optional[List[str]] = None,
    # Dataset search parameters (for search_datasets)
    product_title: Optional[str] = None,
    product_description: Optional[str] = None,
    product_short_name: Optional[str] = None,
    include_files: Optional[bool] = True,
    latest: Optional[bool] = False,
    labels: Optional[str] = None,
    categories: Optional[str] = None,
    datasets: Optional[str] = None,
    file_types: Optional[str] = None,
    # Dataset product parameters (for get_dataset_product)
    product_id: Optional[str] = None,
    file_data_from_date: Optional[str] = None,
    file_data_to_date: Optional[str] = None
) -> Dict[str, Any]:
    """Unified tool for USPTO patent operations: search patents and applications, retrieve full documents,
    download PDFs, and access metadata from USPTO databases.

    Use the method parameter to specify the operation type.

    Available methods:
    - ppubs_get_full_document: Get full patent document by GUID
    - ppubs_get_patent_by_number: Get granted patent's full text by number
    - ppubs_download_patent_pdf: Download granted patent as PDF
    - get_app: Get patent application data by number
    - search_applications: Search patent applications with query parameters
    - search_applications_post: Search patent applications with JSON payload
    - download_applications: Download patent applications with query parameters
    - download_applications_post: Download patent applications with JSON payload
    - get_app_metadata: Get application metadata
    - get_app_adjustment: Get patent term adjustment data
    - get_app_assignment: Get assignment data
    - get_app_attorney: Get attorney/agent information
    - get_app_continuity: Get continuity data
    - get_app_foreign_priority: Get foreign priority claims
    - get_app_transactions: Get transaction history
    - get_app_documents: Get document details
    - get_app_associated_documents: Get associated documents
    - get_status_codes: Search for status codes
    - get_status_codes_post: Search status codes with JSON payload
    - search_datasets: Search bulk dataset products
    - get_dataset_product: Get specific dataset product

    Args:
        method: The operation to perform (required)
        limit: For search_*: Maximum results to return (default: 25)
        sort: For search_*: Sort order
        guid: For ppubs_get_full_document: Document unique identifier
        source_type: For ppubs_get_full_document: Document type (USPAT or US-PGPUB)
        publication_number: For ppubs_get_full_document: convenience — when guid/
            source_type are omitted, resolve the document from this publication
            number (same pub->guid lookup as ppubs_get_patent_by_number).
        patent_number: For ppubs_get_patent_by_number/ppubs_download_patent_pdf: Patent number.
            Also accepted as an alias of publication_number for ppubs_get_full_document.
        app_num: For get_app_*: U.S. Patent Application Number (e.g., 14412875)
        q: For search_*/download_*: Search query string
        offset: For search_*/download_*: Starting position (default: 0)
        facets: For search_*/download_*: Fields to facet upon
        fields: For search_*/download_*: Fields to include in response
        filters: For search_*/download_*: Filter conditions
        range_filters: For search_*/download_*: Range filter conditions
        format: For download_*: Download format (json or csv, default: json)
        filters_list: For *_post: List of filter objects
        range_filters_list: For *_post: List of range filter objects
        sort_list: For *_post: List of sort objects
        fields_list: For *_post: List of field names
        facets_list: For *_post: List of facet field names
        product_title: For search_datasets: Specific product title
        product_description: For search_datasets: Specific product description
        product_short_name: For search_datasets: Product identifier
        include_files: For search_datasets/get_dataset_product: Include files (default: true)
        latest: For search_datasets/get_dataset_product: Return latest only (default: false)
        labels: For search_datasets: Filter by labels
        categories: For search_datasets: Filter by categories
        datasets: For search_datasets: Filter by datasets
        file_types: For search_datasets: Filter by file types
        product_id: For get_dataset_product: Product identifier
        file_data_from_date: For get_dataset_product: Filter files from date (YYYY-MM-DD)
        file_data_to_date: For get_dataset_product: Filter files to date (YYYY-MM-DD)
    """

    # Route to the appropriate method.
    # Search methods are retired (plans/patentmcp_search-dispatcher DD-6):
    # all patent SEARCHING goes through the single patent_search dispatcher.
    if method in ("ppubs_search_patents", "ppubs_search_applications"):
        return {"success": False,
                "message": "search methods retired — use patent_search"}

    elif method == "ppubs_get_full_document":
        if guid and source_type:
            return await ppubs_client.get_document(guid, source_type)
        # Convenience: resolve via publication/patent number (same pub->guid
        # lookup used by ppubs_get_patent_by_number) when no guid is supplied.
        pub_for_doc = publication_number or patent_number
        if not pub_for_doc:
            return {"error": True,
                    "message": ("guid+source_type, or publication_number "
                                "(patent_number alias), is required for "
                                "ppubs_get_full_document")}
        patent = await _ppubs_resolve_patent_by_number(pub_for_doc)
        if patent.get("error"):
            return patent
        return await ppubs_client.get_document(patent["guid"], patent["type"])

    elif method == "ppubs_get_patent_by_number":
        if not patent_number:
            return {"error": True, "message": "patent_number parameter is required for ppubs_get_patent_by_number"}

        patent = await _ppubs_resolve_patent_by_number(patent_number)
        if patent.get("error"):
            return patent

        # Now get the full document
        return await ppubs_client.get_document(patent["guid"], patent["type"])

    elif method == "ppubs_download_patent_pdf":
        if not patent_number:
            return {"error": True, "message": "patent_number parameter is required for ppubs_download_patent_pdf"}

        # Convert to string if integer
        patent_number = str(patent_number)

        # First search for the patent using specific field
        search_query = f'patentNumber:"{patent_number}"'
        logger.info(f"Searching for patent with query: {search_query}")

        result = await ppubs_client.run_query(
            query=search_query,
            sources=["USPAT"],
            limit=1
        )

        if result.get("error", False):
            return result

        # Handle different response structures
        if result.get("patents") and len(result["patents"]) > 0:
            patent = result["patents"][0]
        elif result.get("docs") and len(result["docs"]) > 0:
            patent = result["docs"][0]
        else:
            # Try alternative query format
            alternative_query = f'"{patent_number}".pn.'
            logger.info(f"No results found, trying alternative query: {alternative_query}")

            result = await ppubs_client.run_query(
                query=alternative_query,
                sources=["USPAT"],
                limit=1
            )

            if result.get("error", False):
                return result

            if not result.get("patents") and not result.get("docs"):
                return {
                    "error": True,
                    "message": f"Patent {patent_number} not found"
                }

            if result.get("patents") and len(result["patents"]) > 0:
                patent = result["patents"][0]
            elif result.get("docs") and len(result["docs"]) > 0:
                patent = result["docs"][0]
            else:
                return {
                    "error": True,
                    "message": f"Patent {patent_number} not found"
                }

        # Handle different field naming in the response
        image_location = patent.get("imageLocation", patent.get("document_structure", {}).get("image_location"))
        page_count = patent.get("pageCount", patent.get("document_structure", {}).get("page_count"))

        if not image_location or not page_count:
            return {
                "error": True,
                "message": "Missing image location or page count information"
            }

        # Download the PDF
        return await ppubs_client.download_image(
            patent["guid"],
            image_location,
            page_count,
            patent["type"]
        )

    # API.USPTO.GOV methods
    elif method == "get_app":
        if not app_num:
            return {"error": True, "message": "app_num parameter is required for get_app"}
        url = f"{USPTO_API_BASE}/api/v1/patent/applications/{app_num}"
        return await api_client.make_request(url)

    elif method == "search_applications":
        params = {
            "q": q,
            "sort": sort,
            "offset": offset,
            "limit": limit,
            "facets": facets,
            "fields": fields,
            "filters": filters,
            "rangeFilters": range_filters
        }

        query_string = api_client.build_query_string(params)
        url = f"{USPTO_API_BASE}/api/v1/patent/applications/search"
        if query_string:
            url = f"{url}?{query_string}"

        return await api_client.make_request(url)

    elif method == "search_applications_post":
        data = {
            "q": q,
            "filters": filters_list,
            "rangeFilters": range_filters_list,
            "sort": sort_list,
            "fields": fields_list,
            "pagination": {"offset": offset, "limit": limit},
            "facets": facets_list
        }

        # Remove None values
        data = {k: v for k, v in data.items() if v is not None}

        url = f"{USPTO_API_BASE}/api/v1/patent/applications/search"
        return await api_client.make_request(url, method="POST", data=data)

    elif method == "download_applications":
        params = {
            "q": q,
            "sort": sort,
            "offset": offset,
            "limit": limit,
            "fields": fields,
            "filters": filters,
            "rangeFilters": range_filters,
            "format": format
        }

        query_string = api_client.build_query_string(params)
        url = f"{USPTO_API_BASE}/api/v1/patent/applications/search/download"
        if query_string:
            url = f"{url}?{query_string}"

        return await api_client.make_request(url)

    elif method == "download_applications_post":
        data = {
            "q": q,
            "filters": filters_list,
            "rangeFilters": range_filters_list,
            "sort": sort_list,
            "fields": fields_list,
            "pagination": {"offset": offset, "limit": limit},
            "format": format
        }

        # Remove None values
        data = {k: v for k, v in data.items() if v is not None}

        url = f"{USPTO_API_BASE}/api/v1/patent/applications/search/download"
        return await api_client.make_request(url, method="POST", data=data)

    elif method == "get_app_metadata":
        if not app_num:
            return {"error": True, "message": "app_num parameter is required for get_app_metadata"}
        url = f"{USPTO_API_BASE}/api/v1/patent/applications/{app_num}/meta-data"
        return await api_client.make_request(url)

    elif method == "get_app_adjustment":
        if not app_num:
            return {"error": True, "message": "app_num parameter is required for get_app_adjustment"}
        url = f"{USPTO_API_BASE}/api/v1/patent/applications/{app_num}/adjustment"
        return await api_client.make_request(url)

    elif method == "get_app_assignment":
        if not app_num:
            return {"error": True, "message": "app_num parameter is required for get_app_assignment"}
        url = f"{USPTO_API_BASE}/api/v1/patent/applications/{app_num}/assignment"
        return await api_client.make_request(url)

    elif method == "get_app_attorney":
        if not app_num:
            return {"error": True, "message": "app_num parameter is required for get_app_attorney"}
        url = f"{USPTO_API_BASE}/api/v1/patent/applications/{app_num}/attorney"
        return await api_client.make_request(url)

    elif method == "get_app_continuity":
        if not app_num:
            return {"error": True, "message": "app_num parameter is required for get_app_continuity"}
        url = f"{USPTO_API_BASE}/api/v1/patent/applications/{app_num}/continuity"
        return await api_client.make_request(url)

    elif method == "get_app_foreign_priority":
        if not app_num:
            return {"error": True, "message": "app_num parameter is required for get_app_foreign_priority"}
        url = f"{USPTO_API_BASE}/api/v1/patent/applications/{app_num}/foreign-priority"
        return await api_client.make_request(url)

    elif method == "get_app_transactions":
        if not app_num:
            return {"error": True, "message": "app_num parameter is required for get_app_transactions"}
        url = f"{USPTO_API_BASE}/api/v1/patent/applications/{app_num}/transactions"
        return await api_client.make_request(url)

    elif method == "get_app_documents":
        if not app_num:
            return {"error": True, "message": "app_num parameter is required for get_app_documents"}
        url = f"{USPTO_API_BASE}/api/v1/patent/applications/{app_num}/documents"
        return await api_client.make_request(url)

    elif method == "get_app_associated_documents":
        if not app_num:
            return {"error": True, "message": "app_num parameter is required for get_app_associated_documents"}
        url = f"{USPTO_API_BASE}/api/v1/patent/applications/{app_num}/associated-documents"
        return await api_client.make_request(url)

    elif method == "get_status_codes":
        params = {
            "q": q,
            "offset": offset,
            "limit": limit,
        }

        query_string = api_client.build_query_string(params)
        url = f"{USPTO_API_BASE}/api/v1/patent/status-codes"
        if query_string:
            url = f"{url}?{query_string}"

        return await api_client.make_request(url)

    elif method == "get_status_codes_post":
        data = {
            "q": q,
            "pagination": {"offset": offset, "limit": limit}
        }

        # Remove None values
        data = {k: v for k, v in data.items() if v is not None}

        url = f"{USPTO_API_BASE}/api/v1/patent/status-codes"
        return await api_client.make_request(url, method="POST", data=data)

    elif method == "search_datasets":
        params = {
            "q": q,
            "productTitle": product_title,
            "productDescription": product_description,
            "productShortName": product_short_name,
            "offset": offset,
            "limit": limit,
            "facets": facets,
            "includeFiles": include_files,
            "latest": latest,
            "labels": labels,
            "categories": categories,
            "datasets": datasets,
            "fileTypes": file_types
        }

        query_string = api_client.build_query_string(params)
        url = f"{USPTO_API_BASE}/api/v1/datasets/products/search"
        if query_string:
            url = f"{url}?{query_string}"

        return await api_client.make_request(url)

    elif method == "get_dataset_product":
        if not product_id:
            return {"error": True, "message": "product_id parameter is required for get_dataset_product"}

        params = {
            "fileDataFromDate": file_data_from_date,
            "fileDataToDate": file_data_to_date,
            "offset": offset,
            "limit": limit,
            "includeFiles": include_files,
            "latest": latest
        }

        query_string = api_client.build_query_string(params)
        url = f"{USPTO_API_BASE}/api/v1/datasets/products/{product_id}"
        if query_string:
            url = f"{url}?{query_string}"

        return await api_client.make_request(url)

    else:
        return {"error": True, "message": f"Unknown method: {method}"}


# =====================================================================
# Google Patents Tools
# =====================================================================

@mcp.tool(annotations=_RO)
async def google_get_patent(publication_number: str) -> Dict[str, Any]:
    """Get full patent details from Google Patents by publication number

    Retrieves complete patent information including title, abstract, dates,
    inventors, assignees, classifications, and more.

    Args:
        publication_number: Patent publication number (e.g., US-9876543-B2)

    Returns:
        Dictionary containing complete patent details
    """
    try:
        result = await google_bq_client.get_patent_by_number(publication_number)
        return result
    except BudgetExceededError as e:
        logger.warning(f"BigQuery blocked by budget gate: {str(e)}")
        return {
            "success": False,
            "error_code": "BQ_BUDGET_EXCEEDED",
            "monthly_used_bytes": e.used_bytes,
            "monthly_budget_bytes": e.budget_bytes,
            "usage_source": e.source,
            "suggestion": "BigQuery monthly budget exhausted. Use GPSS/EPO/PPUBS instead.",
        }
    except Exception as e:
        logger.error(f"Error fetching patent {publication_number}: {str(e)}")
        return ApiError.create(
            message=f"Failed to fetch patent: {str(e)}", status_code=500
        )


@mcp.tool(annotations=_RO)
async def google_get_patent_claims(publication_number: str) -> Dict[str, Any]:
    """Get patent claims from Google Patents by publication number

    Retrieves all claims for the specified patent, including claim numbers
    and full claim text.

    Args:
        publication_number: Patent publication number (e.g., US-9876543-B2)

    Returns:
        Dictionary containing claim number and text for each claim
    """
    try:
        result = await google_bq_client.get_patent_claims(publication_number)
        return result
    except BudgetExceededError as e:
        logger.warning(f"BigQuery blocked by budget gate: {str(e)}")
        return {
            "success": False,
            "error_code": "BQ_BUDGET_EXCEEDED",
            "monthly_used_bytes": e.used_bytes,
            "monthly_budget_bytes": e.budget_bytes,
            "usage_source": e.source,
            "suggestion": "BigQuery monthly budget exhausted. Use GPSS/EPO/PPUBS instead.",
        }
    except Exception as e:
        logger.error(f"Error fetching claims for {publication_number}: {str(e)}")
        return ApiError.create(
            message=f"Failed to fetch claims: {str(e)}", status_code=500
        )


@mcp.tool(annotations=_RO)
async def google_get_patent_description(publication_number: str) -> Dict[str, Any]:
    """Get patent description from Google Patents by publication number

    Retrieves the detailed description section of the patent document.

    Args:
        publication_number: Patent publication number (e.g., US-9876543-B2)

    Returns:
        Dictionary containing patent description text
    """
    try:
        result = await google_bq_client.get_patent_description(publication_number)
        return result
    except BudgetExceededError as e:
        logger.warning(f"BigQuery blocked by budget gate: {str(e)}")
        return {
            "success": False,
            "error_code": "BQ_BUDGET_EXCEEDED",
            "monthly_used_bytes": e.used_bytes,
            "monthly_budget_bytes": e.budget_bytes,
            "usage_source": e.source,
            "suggestion": "BigQuery monthly budget exhausted. Use GPSS/EPO/PPUBS instead.",
        }
    except Exception as e:
        logger.error(
            f"Error fetching description for {publication_number}: {str(e)}"
        )
        return ApiError.create(
            message=f"Failed to fetch description: {str(e)}", status_code=500
        )


@mcp.tool(annotations=_RO)
async def google_budget_status() -> Dict[str, Any]:
    """Report the current month's BigQuery usage against the configured budget.

    BigQuery is billed per bytes scanned. When month-to-date usage exceeds the
    budget, ALL BigQuery tools (google_get_patent*) are hard-blocked. Use this
    to check whether BigQuery retrieval is currently available before relying on
    it as a fallback source for claims/description text.

    Returns:
        Dict with used_bytes, budget_bytes, exceeded (bool), source
        (authoritative | cached | cached-degraded | none), and
        last_reconciled_at.
    """
    try:
        if google_bq_client.client is None:
            return {
                "success": False,
                "error": "BigQuery client not initialized. Check Google Cloud credentials.",
            }
        usage = await google_bq_client.get_monthly_usage(force_reconcile=True)
        return {"success": True, **usage}
    except Exception as e:
        logger.error(f"Error fetching BigQuery budget status: {str(e)}")
        return ApiError.create(
            message=f"Failed to fetch budget status: {str(e)}", status_code=500
        )


# =====================================================================
# Google Patents (web endpoint) Tools — ranked search, figures, PDF
# =====================================================================

async def _gpatents_search_impl(
    query: str,
    countries: Optional[List[str]] = None,
    num: Optional[int] = 10,
    page: Optional[int] = 0,
    before: Optional[str] = None,
    after: Optional[str] = None,
    status: Optional[str] = None,
    type: Optional[str] = None,
) -> Dict[str, Any]:
    """Relevance-ranked prior-art search via Google Patents (patents.google.com).

    WARNING: Google Patents is highly sensitive to scraping. Use ONLY as a last resort
    for single-file retrieval. DO NOT use for batch processing or automated crawling.
    
    Unlike the BigQuery tools (billed per bytes scanned), this is free and returns
    Google's semantic ranking plus a representative-figure thumbnail and full-PDF
    link for every hit. Default country coverage is US/CN/TW.

    Args:
        query: free-text query; Google ranks results by semantic relevance.
        countries: country codes to include (default ["US","CN","TW"]).
        num: results per page (max ~100).
        page: 0-based page index for pagination.
        before/after: date bounds, e.g. "priority:20200101", "publication:20240101".
        status: "GRANT" or "APPLICATION".
        type: "PATENT".

    Returns a dict with total_num_results and a `results` list; each item has
    publication_number, title, snippet, dates, inventor, assignee,
    representative_figure_url, pdf_url, num_figures, family_country_status.
    """
    return await gpatents_client.search(
        query=query,
        countries=countries,
        num=num or 10,
        page=page or 0,
        before=before,
        after=after,
        status=status,
        type_=type,
    )


def _handle(entry, rel: Optional[str] = None) -> Dict[str, Any]:
    """Shape a token-store entry into a docxmcp-style download handle."""
    rel = rel or entry.filename
    return {
        "success": True,
        "token": entry.token,
        "rel": rel,
        "download_url": _file_server.download_url(entry.token, rel),
        "bytes": entry.size_bytes,
        "sha256": entry.sha256,
    }


def _get_db_root():
    import os
    from pathlib import Path
    env_root = os.environ.get("PATENTS_DB_ROOT")
    if env_root:
        return Path(env_root)

    curr = Path(__file__).resolve()
    for _ in range(10):
        if (curr / ".mcp.json").is_file():
            return curr / "patentdb"
        curr = curr.parent
    # Fallback to 5 levels up
    return Path(__file__).resolve().parent.parent.parent.parent.parent / "patentdb"


def _get_patent_country_and_normalized_no(publication_number: str) -> tuple[str, str]:
    import re
    pat = re.sub(r'\s+', '', publication_number).upper()
    
    # Determine country
    country = "US"  # Default fallback
    if pat.startswith("TW"):
        country = "TW"
        pat = pat[2:]
    elif pat.startswith("US"):
        country = "US"
        pat = pat[2:]
    elif pat.startswith("EP"):
        country = "EP"
        pat = pat[2:]
    elif pat.startswith("WO"):
        country = "WO"
        pat = pat[2:]
    elif pat.startswith("CN"):
        country = "CN"
        pat = pat[2:]
    elif re.match(r'^[IMD]\d+', pat):
        country = "TW"
    elif re.match(r'^\d{9}$', pat):  # TW application number (9 digits)
        country = "TW"
        
    # Normalize patent number
    m_cert = re.match(r'^([IMD]\d+)[A-Za-z]*$', pat)
    if m_cert:
        pat = m_cert.group(1)
    else:
        m_app = re.match(r'^(\d+)[A-Za-z]*$', pat)
        if m_app:
            pat = m_app.group(1)
            
    return country, pat


def _find_local_patent_cache(country: str, norm_pat: str, file_type: str):
    filename = f"specification.{file_type}"
    db_root = _get_db_root()
    path = db_root / country / norm_pat / filename
    if path.is_file():
        return path
    return None


def _save_local_patent_cache(
    country: str,
    norm_pat: str,
    file_type: str,
    data: bytes,
    *,
    figure_name: Optional[str] = None,
    biblio: Optional[Dict[str, Any]] = None,
    acquisition_cost: str = "low",
    source: Optional[str] = None,
) -> Optional[str]:
    """Write-through blob cache + patentdb register side-effect.

    file_type: "pdf" / "xml" → specification.<type>; "figure" → figures/<figure_name>.
    biblio: optional full bibliographic fields to enrich metadata.json + patentdb.
    Returns the relative blob path under patentdb root (for register), or None.
    """
    import json
    import time
    import hashlib

    db_root = _get_db_root()
    target_dir = db_root / country / norm_pat
    rel_path = None
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        if file_type == "figure":
            fig_dir = target_dir / "figures"
            fig_dir.mkdir(parents=True, exist_ok=True)
            fname = figure_name or "representative.png"
            (fig_dir / fname).write_bytes(data)
            rel_path = f"{country}/{norm_pat}/figures/{fname}"
        else:
            filename = f"specification.{file_type}"
            (target_dir / filename).write_bytes(data)
            rel_path = f"{country}/{norm_pat}/{filename}"

        # metadata.json — enrich with full biblio when provided, else keep/seed stub
        meta_path = target_dir / "metadata.json"
        meta_data: Dict[str, Any] = {}
        if meta_path.is_file():
            try:
                meta_data = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta_data = {}
        if not meta_data:
            meta_data = {
                "publication_number": f"{country}{norm_pat}",
                "normalized_number": norm_pat,
                "country": country,
                "cached_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        if biblio:
            # only fill missing keys (progressive merge, do not clobber)
            for k, v in biblio.items():
                if v and not meta_data.get(k):
                    meta_data[k] = v
        meta_path.write_text(json.dumps(meta_data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to save local patent cache for {country}/{norm_pat}: {e}")
        return None

    # patentdb register side-effect (DD-7): never block the download path
    try:
        sha = hashlib.sha256(data).hexdigest()
        blobs: Dict[str, Any] = {}
        if file_type == "figure":
            blobs["figures"] = [{"name": figure_name or "representative.png",
                                 "path": rel_path, "sha256": sha}]
        else:
            blobs[file_type] = {"path": rel_path, "sha256": sha}
        _pdb.put(
            f"{country}{norm_pat}",
            fields=biblio or {},
            blobs=blobs,
            acquisition_cost=acquisition_cost,
        )
    except Exception as e:
        logger.warning(f"patentdb register failed for {country}/{norm_pat}: {e}")

    return rel_path


@mcp.tool()
async def build_screening_table(
    cpc: Optional[str] = None,
    keyword: Optional[str] = None,
    databases: Optional[List[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    purpose: str = "landscape",
    extra_fields: Optional[List[str]] = None,
    exclude_fields: Optional[List[str]] = None,
    max_rows: int = 300,
    num: int = 100,
    allow_scraping: bool = False,
    filename: str = "screening.csv",
) -> Dict[str, Any]:
    """[LANDED → skills/patentworks/scripts/screening_build.py]

    R13 compute/landing split: screening-table construction is a deterministic,
    stdlib-only record→CSV transform (dedup_by_family → resolve_columns →
    build_csv) that no longer runs in-container. Run `patent_search` to get the
    records JSON, then build the CSV locally with the landing script (agent uid,
    host filesystem, zero model-context passthrough). Returns a TOOL_LANDED
    redirect envelope; the old in-container logic is retired (removed 0.5.0).
    """
    return {
        "success": False,
        "error_code": "TOOL_LANDED",
        "landing": {
            "script": "skills/patentworks/scripts/screening_build.py",
            "usage": (
                "# 1) get records via patent_search, save to records.json\n"
                "python3 skills/patentworks/scripts/screening_build.py "
                "--in records.json --out screening.csv "
                "--purpose landscape --source records"
            ),
        },
    }


@mcp.tool()
async def stage_file(path: str, filename: Optional[str] = None) -> Dict[str, Any]:
    """[LANDED → WebDAV working cache; direct staging retired]

    R13/WebDAV: "stage a local file into the token store" is obsoleted by the
    WebDAV working cache. Provision a subject-anchored cache with
    `cache_provision`, then PUT the file over WebDAV (the mounted cache tree);
    the deliverable lands via `cache_export`. Returns a TOOL_LANDED envelope
    with a null script (no landing script — the DAV path replaces it).
    """
    return {
        "success": False,
        "error_code": "TOOL_LANDED",
        "landing": {
            "script": None,
            "usage": (
                "provision a cache (cache_provision(subject_id=...)) then PUT the "
                "file over WebDAV to the mounted cache tree; direct staging into "
                "the token store is retired — use cache_export to land deliverables."
            ),
        },
    }


@mcp.tool(annotations=_RO)
async def gpatents_get(
    publication_number: str,
    include_description: bool = False,
) -> Dict[str, Any]:
    """Fetch a patent's full abstract + claims from its Google Patents page.

    WARNING: Google Patents is highly sensitive to scraping. Use ONLY as a last resort
    for single-file retrieval. DO NOT use for batch processing or automated crawling.
    
    Use after patent_search to pull the complete claims (the search snippet is
    only an excerpt). CN/JP/etc. are returned as Google's English machine
    translation. abstract + claims are returned in-band (small). When
    include_description=True the large full text is instead LANDED in the token
    store and the response carries a download handle (token/rel/download_url),
    NOT the description bytes.

    consider: patentmcp_kb_query — recall known scraping failure modes and
    retrieval ladders before reaching for this last-resort tool.
    """
    result = await gpatents_client.get_patent(publication_number, include_description)
    if not result.get("success") or not include_description:
        return result
    md = gpatents_client.fulltext_markdown(result)
    entry = token_store.put_bytes(md.encode("utf-8"), f"{publication_number}.md")
    # Return abstract + claims (small, useful) plus the fulltext handle; drop the
    # bulky description from the in-band payload.
    result.pop("description", None)
    result["fulltext"] = _handle(entry)
    return result


from ._pure.claims import clean_html_text, extract_claim1_text  # noqa: E402,F401

@mcp.tool(annotations=_RO)
async def patent_get_claim1(publication_number: Optional[str] = None, full: bool = True,
                            patent_number: Optional[str] = None) -> Dict[str, Any]:
    """Retrieve the cleaned and normalized Claim 1 text for any given patent publication number.

    Automatically handles US (application and grant paths), CN, TW, EP, WIPO, etc.
    with fallback chain: TIPO (GPSS) -> PPUBS/EPO/BigQuery -> Google Patents Scraper.

    Args:
        publication_number: Patent publication number (e.g. US20250252737A1, US11875659B2, TW202403664A).
        full: If True, retrieve the full Claim 1 text without 1000-character truncation (default True).
        patent_number: backward-compatible alias for `publication_number`.

    Returns:
        Dictionary containing success, publication_number, and the claim1 text.
    """
    import re
    pub = publication_number or patent_number
    if not pub:
        return {"success": False, "error": "MISSING_PUBLICATION_NUMBER",
                "detail": "publication_number (or patent_number alias) is required"}
    pat = pub.strip()
    pat_upper = pat.upper()
    
    # ── 1. TIPO GPSS (First Priority for TW, US, CN) ──
    if gpss_client.configured():
        db = None
        if pat_upper.startswith("TW"):
            db = ["TWA", "TWB"]
        elif pat_upper.startswith("US"):
            db = ["USA", "USB"]
        elif pat_upper.startswith("CN"):
            db = ["CNA", "CNB"]
        
        if db is not None:
            try:
                gpss_res = await gpss_client.search(
                    conditions=[GPSSCondition("PN", pat)],
                    databases=db,
                    fields="PN,CL"
                )
                if gpss_res.get("success") and gpss_res.get("data"):
                    api = gpss_res["data"].get("gpss-API", {})
                    patent_content = api.get("patent", {}).get("patentcontent", [])
                    if not isinstance(patent_content, list):
                        patent_content = [patent_content]
                    if patent_content:
                        from patent_mcp_server.epo.client import clean_badgerfish_text
                        claims_root = patent_content[0].get("claims", {})
                        claim_data = claims_root.get("claim", {})
                        
                        claim_candidates = []
                        if isinstance(claim_data, list):
                            for c in claim_data:
                                if isinstance(c, dict):
                                    ct = c.get("claim-text")
                                    txt = clean_badgerfish_text(ct)
                                    if txt:
                                        claim_candidates.append(txt)
                        elif isinstance(claim_data, dict):
                            ct = claim_data.get("claim-text")
                            if isinstance(ct, list):
                                for item in ct:
                                    txt = clean_badgerfish_text(item)
                                    if txt:
                                        claim_candidates.append(txt)
                            else:
                                txt = clean_badgerfish_text(ct)
                                if txt:
                                    claim_candidates.append(txt)
                                    
                        claim1 = ""
                        for candidate in claim_candidates:
                            cand_lower = candidate.strip().lower().rstrip(":")
                            if cand_lower not in {
                                "what is claimed is", "what we claim is", "what i claim is",
                                "we claim", "i claim", "claims", "what is claimed",
                                "what i claim", "what we claim", "claim", "the claims"
                            }:
                                claim1 = candidate
                                break
                        if not claim1 and claim_candidates:
                            claim1 = claim_candidates[0]
                            
                        if claim1:
                            if not full and len(claim1) > 1000:
                                claim1 = claim1[:1000].strip() + "..."
                            return {"success": True, "publication_number": pat, "claim1": claim1.strip(), "source": "tipo"}
            except Exception as e:
                logger.warning(f"GPSS query failed for {pat} (primary): {str(e)}")

    # ── 2. Official APIs / BigQuery (Second Priority) ──
    # A) US Patents via USPTO PPUBS
    if pat_upper.startswith("US"):
        clean_num = re.sub(r'^(US)', '', pat, flags=re.IGNORECASE)
        clean_num = re.sub(r'[A-Z]\d*$', '', clean_num, flags=re.IGNORECASE)
        try:
            if pat_upper.endswith("A1") or pat_upper.endswith("A2") or pat_upper.endswith("A9") or (len(clean_num) == 11 and clean_num.startswith(("201", "202"))):
                sources = ["US-PGPUB"]
                query = f'publicationNumber:"{clean_num}"'
            else:
                sources = ["USPAT"]
                query = f'patentNumber:"{clean_num}"'
                
            search_res = await ppubs_client.run_query(query=query, sources=sources, limit=1)
            docs = search_res.get("patents", []) or search_res.get("docs", [])
            if not docs:
                search_res = await ppubs_client.run_query(query=f'"{clean_num}".pn.', sources=sources, limit=1)
                docs = search_res.get("patents", []) or search_res.get("docs", [])
            
            if docs:
                doc = docs[0]
                res = await ppubs_client.get_document(doc["guid"], doc.get("type", sources[0]))
                if "claimsHtml" in res:
                    plain_claims = clean_html_text(res["claimsHtml"])
                    claim1 = extract_claim1_text(plain_claims, full=full)
                    return {"success": True, "publication_number": pat, "claim1": claim1, "source": "uspto"}
        except Exception as e:
            logger.warning(f"USPTO PPUBS failed for {pat}: {str(e)}")

    # B) EP Patents via EPO OPS
    if pat_upper.startswith("EP") and epo_client.configured():
        try:
            epo_res = await epo_client.claims(pat)
            if epo_res.get("success") and epo_res.get("found") and epo_res.get("claim1"):
                claim1 = epo_res["claim1"]
                if not full and len(claim1) > 1000:
                    claim1 = claim1[:1000].strip() + "..."
                return {"success": True, "publication_number": pat, "claim1": claim1, "source": "epo"}
        except Exception as e:
            logger.warning(f"EPO OPS claims query failed for {pat}: {str(e)}")

    # C) BigQuery
    if google_bq_client.client is not None:
        try:
            m = re.match(r'^([A-Z]{2})(\d+)([A-Z]\d*)?$', pat, re.IGNORECASE)
            bq_pat = f"{m.group(1).upper()}-{m.group(2)}-{m.group(3) or 'A'}" if m else pat
            bq_res = await google_bq_client.get_patent_claims(bq_pat)
            if bq_res.get("success") and bq_res.get("claims"):
                claims_list = bq_res["claims"]
                if claims_list:
                    claim1 = claims_list[0].get("claim_text", "")
                    claim1 = extract_claim1_text(clean_html_text(claim1), full=full)
                    return {"success": True, "publication_number": pat, "claim1": claim1, "source": "bigquery"}
        except BudgetExceededError as e:
            # BQ is a fallback source here; when the monthly budget is exhausted
            # we skip it (logged) and let the chain fall through to GPSS.
            logger.warning(f"BigQuery skipped for {pat} (budget exhausted): {str(e)}")
        except Exception as e:
            logger.warning(f"BigQuery claims query failed for {pat}: {str(e)}")

    # D) TIPO GPSS as general fallback if not run yet
    if gpss_client.configured() and not (pat_upper.startswith("TW") or pat_upper.startswith("US") or pat_upper.startswith("CN")):
        try:
            gpss_res = await gpss_client.search(
                conditions=[GPSSCondition("PN", pat)],
                fields="PN,CL"
            )
            if gpss_res.get("success") and gpss_res.get("data"):
                api = gpss_res["data"].get("gpss-API", {})
                patent_content = api.get("patent", {}).get("patentcontent", [])
                if not isinstance(patent_content, list):
                    patent_content = [patent_content]
                if patent_content:
                    from patent_mcp_server.epo.client import clean_badgerfish_text
                    claims_root = patent_content[0].get("claims", {})
                    claim_data = claims_root.get("claim", {})
                    
                    claim_candidates = []
                    if isinstance(claim_data, list):
                        for c in claim_data:
                            if isinstance(c, dict):
                                ct = c.get("claim-text")
                                txt = clean_badgerfish_text(ct)
                                if txt:
                                    claim_candidates.append(txt)
                    elif isinstance(claim_data, dict):
                        ct = claim_data.get("claim-text")
                        if isinstance(ct, list):
                            for item in ct:
                                txt = clean_badgerfish_text(item)
                                if txt:
                                    claim_candidates.append(txt)
                        else:
                            txt = clean_badgerfish_text(ct)
                            if txt:
                                claim_candidates.append(txt)
                                
                    claim1 = ""
                    for candidate in claim_candidates:
                        cand_lower = candidate.strip().lower().rstrip(":")
                        if cand_lower not in {
                            "what is claimed is", "what we claim is", "what i claim is",
                            "we claim", "i claim", "claims", "what is claimed",
                            "what i claim", "what we claim", "claim", "the claims"
                        }:
                            claim1 = candidate
                            break
                    if not claim1 and claim_candidates:
                        claim1 = claim_candidates[0]
                        
                    if claim1:
                        if not full and len(claim1) > 1000:
                            claim1 = claim1[:1000].strip() + "..."
                        return {"success": True, "publication_number": pat, "claim1": claim1.strip(), "source": "tipo"}
        except Exception as e:
            logger.warning(f"GPSS general fallback failed for {pat}: {str(e)}")

    # ── 3. Google Patents Scraper (Last Resort Fallback) ──
    try:
        gpat_res = await gpatents_client.get_patent(pat, include_description=False)
        if gpat_res.get("success") and gpat_res.get("claims"):
            claims_list = gpat_res["claims"]
            if claims_list:
                claim1 = claims_list[0].get("text", "")
                claim1 = extract_claim1_text(clean_html_text(claim1), full=full)
                return {"success": True, "publication_number": pat, "claim1": claim1, "source": "google_patents"}
            return {"success": False, "publication_number": pat, "error": "No claims found in gpatents response."}
        else:
            return {"success": False, "publication_number": pat, "error": gpat_res.get("error", "Failed to fetch from gpatents.")}
    except Exception as e:
        return {"success": False, "publication_number": pat, "error": f"Scraper error: {str(e)}"}


@mcp.tool(annotations=_RO)
async def ppubs_batch_get_claims(publication_numbers: Optional[List[str]] = None,
                                 patent_numbers: Optional[List[str]] = None) -> Dict[str, Any]:
    """Batch retrieve the Claim 1 text for a list of patent publication numbers.

    Queries TIPO (GPSS) first, then official APIs / BigQuery, and Google Patents as a last resort.
    Stages the compiled JSON mapping in the token store and returns a docxmcp-style download handle.

    Args:
        publication_numbers: List of patent publication numbers (e.g. ["US11875659B2", "TW202403664A"]).
        patent_numbers: backward-compatible alias for `publication_numbers`.

    Returns:
        Dictionary containing success, the claims mapping, and the token store handle.

    consider: patentmcp_kb_query — recall per-source claim-retrieval failure
    modes (e.g. GPSS empty TW biblio) before batch-pulling claims.
    """
    import json
    import asyncio

    pubs = publication_numbers or patent_numbers
    if not pubs:
        return {"success": False, "error": "MISSING_PUBLICATION_NUMBERS",
                "detail": "publication_numbers (or patent_numbers alias) is required"}

    if len(pubs) > 100:
        return {"success": False, "error": "Batch size limit exceeded. Maximum allowed is 100."}
        
    results = {}
    for pub in pubs:
        pub = pub.strip()
        if not pub:
            continue
            
        try:
            res = await patent_get_claim1(pub, full=True)
            results[pub] = res
        except Exception as e:
            results[pub] = {"success": False, "publication_number": pub, "error": str(e)}

        # plan gpss-session-reuse-batch (extend): the old blanket 0.5s sleep is
        # gone — each crawler surface now self-paces through its own
        # SoftScrapePolicy (GPSS _GPSS_POLICY, ppubs PpubsClient.policy), and
        # official APIs (BigQuery) are deliberately not throttled. A fixed sleep
        # here would just double-pace the scraper paths.
        
    data = json.dumps(results, indent=2, ensure_ascii=False).encode("utf-8")
    entry = token_store.put_bytes(data, "claims.json")
    handle = _handle(entry)
    
    return {
        "success": True,
        "claims": results,
        "token": handle["token"],
        "rel": handle["rel"],
        "download_url": handle["download_url"],
        "bytes": handle["bytes"],
        "sha256": handle["sha256"]
    }


@mcp.tool()
async def gpatents_download_pdf(pdf_url: str, filename: Optional[str] = None) -> Dict[str, Any]:
    """Download a patent's full PDF into the token store.

    Pass the `pdf_url` from a patent_search (gpatents-source) result. Returns a docxmcp-style
    handle {token, rel, download_url, bytes, sha256}; the PDF bytes are stored,
    never returned through the model context. Use the token with docxmcp's
    `from_token` to pull the PDF into a report by reference.
    """
    try:
        data = await gpatents_client.fetch_bytes(pdf_url)
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": str(e)}
    name = filename or pdf_url.rsplit("/", 1)[-1] or "patent.pdf"
    entry = token_store.put_bytes(data, name)
    return _handle(entry)


@mcp.tool()
async def gpatents_download_figure(figure_url: str, filename: Optional[str] = None) -> Dict[str, Any]:
    """Download a representative-figure image into the token store.

    Pass the `representative_figure_url` from a patent_search (gpatents-source) result. Returns a
    docxmcp-style handle {token, rel, download_url, bytes, sha256}; the image
    bytes are stored, never returned through the model context.

    BR_20260628 B: Google Storage (patentimages CDN) enables anti-hotlink on
    recently-published patents and returns 403. We surface that as an EXPLICIT
    downgrade signal (CDN_FORBIDDEN) — never silently retry or auto-redirect.
    Callers should switch to extract_representative_figure (PDF pipeline).
    """
    import httpx
    try:
        data = await gpatents_client.fetch_bytes(figure_url)
    except httpx.HTTPStatusError as e:  # noqa: BLE001
        if e.response.status_code == 403:
            return {
                "success": False,
                "error": "CDN_FORBIDDEN",
                "downgrade_hint": "use extract_representative_figure (PDF pipeline)",
                "url": figure_url,
                "http_code": 403,
            }
        return {"success": False, "error": f"HTTP {e.response.status_code}", "url": figure_url}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": str(e)}
    name = filename or figure_url.rsplit("/", 1)[-1] or "figure.png"
    entry = token_store.put_bytes(data, name)
    return _handle(entry)


# ---------------------------------------------------------------------
# extract_representative_figure — PDF -> FIG.1 page -> high-DPI PNG (BR_20260628 D)
# Uses poppler CLI (pdfinfo/pdftotext/pdftoppm), NOT PyMuPDF (AGPL). poppler is a
# native subprocess固化進工具, not an ad-hoc scraping script.
# ---------------------------------------------------------------------

import re as _re_fig

# First-figure markers across EN / zh-Hans / zh-Hant.
_FIG1_PATTERNS = [
    _re_fig.compile(r"\bFIG\.?\s*1\b", _re_fig.IGNORECASE),
    _re_fig.compile(r"\bFIGURE\s*1\b", _re_fig.IGNORECASE),
    _re_fig.compile(r"图\s*1\b"),
    _re_fig.compile(r"圖\s*1\b"),
    _re_fig.compile(r"第\s*1\s*圖"),
    _re_fig.compile(r"第\s*1\s*图"),
]
# Reference-numeral density signal (e.g. "10", "12a") used as a fallback when
# no explicit FIG.1 token is present.
_REFNUM_RE = _re_fig.compile(r"\b\d{1,3}[a-z]?\b")


def _pdf_page_count(pdf_path: str) -> int:
    """Page count via `pdfinfo`. Returns 0 on failure."""
    import subprocess
    try:
        out = subprocess.run(
            ["pdfinfo", pdf_path], capture_output=True, text=True, timeout=30
        )
        for line in out.stdout.splitlines():
            if line.lower().startswith("pages:"):
                return int(line.split(":", 1)[1].strip())
    except Exception as e:  # noqa: BLE001
        logger.warning("pdfinfo failed for %s: %s", pdf_path, e)
    return 0


def _pdf_bytes_page_count(data: bytes) -> int:
    """Page count of an in-memory PDF via `pdfinfo` over a temp file (BR_20260628 F)."""
    import tempfile
    import os as _os
    fd, tmp = tempfile.mkstemp(suffix=".pdf")
    try:
        with _os.fdopen(fd, "wb") as fh:
            fh.write(data)
        return _pdf_page_count(tmp)
    except Exception as e:  # noqa: BLE001
        logger.warning("pdf bytes page count failed: %s", e)
        return 0
    finally:
        try:
            _os.unlink(tmp)
        except OSError:
            pass


def _pdf_page_text(pdf_path: str, page: int) -> str:
    """Extract one page's text via `pdftotext -f N -l N -layout`. '' on failure."""
    import subprocess
    try:
        out = subprocess.run(
            ["pdftotext", "-f", str(page), "-l", str(page), "-layout", pdf_path, "-"],
            capture_output=True, text=True, timeout=30,
        )
        return out.stdout or ""
    except Exception as e:  # noqa: BLE001
        logger.warning("pdftotext failed for %s p%d: %s", pdf_path, page, e)
        return ""


def _locate_figure_page(pdf_path: str) -> Dict[str, Any]:
    """Locate the representative-figure page in a PDF.

    Strategy (BR_20260628 D, DD-4):
      1. Skip page 1 (cover / biblio).
      2. Find the first page whose text matches a FIG.1 marker.
      3. Fallback: the page (>=2) with the highest reference-numeral density.
      4. If neither works (e.g. scanned PDF with no text layer), return None
         page with method='none' — caller fails explicitly, never guesses.
    """
    pages = _pdf_page_count(pdf_path)
    if pages <= 0:
        return {"page": None, "method": "none", "pages": pages}
    start = 2 if pages >= 2 else 1
    best_refnum_page = None
    best_refnum_count = -1
    for p in range(start, pages + 1):
        text = _pdf_page_text(pdf_path, p)
        if not text.strip():
            continue
        for pat in _FIG1_PATTERNS:
            if pat.search(text):
                return {"page": p, "method": "fig1_text", "pages": pages}
        count = len(_REFNUM_RE.findall(text))
        if count > best_refnum_count:
            best_refnum_count = count
            best_refnum_page = p
    if best_refnum_page is not None and best_refnum_count >= 5:
        return {"page": best_refnum_page, "method": "refnum_density_fallback", "pages": pages}
    return {"page": None, "method": "none", "pages": pages}


def _pdf_image_count(pdf_path: str) -> int:
    """Count embedded image XObjects in a PDF via `pdfimages -list` (poppler).

    Used to distinguish a truly empty PDF from a scanned/text-layer-less PDF
    that still contains figure images. Returns 0 on any failure (fail-safe).
    """
    import subprocess
    try:
        out = subprocess.run(
            ["pdfimages", "-list", pdf_path],
            capture_output=True, text=True, timeout=60,
        )
        lines = [ln for ln in out.stdout.splitlines() if ln.strip()]
        # pdfimages -list emits 2 header rows ("page num type ..." + a dashes
        # separator); each remaining row is one image. Guard against short output.
        if len(lines) <= 2:
            return 0
        count = 0
        for ln in lines[2:]:
            first = ln.split(None, 1)[0] if ln.split() else ""
            if first.isdigit():
                count += 1
        return count
    except Exception as e:  # noqa: BLE001
        logger.warning("pdfimages -list failed for %s: %s", pdf_path, e)
        return 0


def _render_page_png(pdf_path: str, page: int, dpi: int = 200) -> Optional[bytes]:
    """Render one PDF page to PNG bytes via `pdftoppm -r DPI -f N -l N -png`."""
    import subprocess
    import tempfile
    import os as _os
    with tempfile.TemporaryDirectory() as td:
        prefix = _os.path.join(td, "page")
        try:
            subprocess.run(
                ["pdftoppm", "-r", str(dpi), "-f", str(page), "-l", str(page),
                 "-png", pdf_path, prefix],
                capture_output=True, text=True, timeout=120, check=True,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("pdftoppm render failed for %s p%d: %s", pdf_path, page, e)
            return None
        for fn in sorted(_os.listdir(td)):
            if fn.endswith(".png"):
                with open(_os.path.join(td, fn), "rb") as fh:
                    return fh.read()
    return None


# ---------------------------------------------------------------------
# PDF identity verification (BR_20260629): a fetched/scraped PDF may be a
# DIFFERENT patent than requested — GPSS fuzzy search landing on a neighbour,
# or a fallback source returning the wrong document. Landing such a PDF as a
# figure source SILENTLY injects a wrong patent's drawing into deliverables
# (CN120543023A once landed CN121094816's spec inner page and reported
# success). Verify the PDF's own publication number (read from its text layer)
# against the requested number before trusting it. Fail LOUD on a confirmed
# mismatch; never silently fall back to the wrong document.
# ---------------------------------------------------------------------

# Publication-number token inside a PDF text layer: 2-letter country + a digit
# core (optionally split by spaces/slashes by pdftotext, with an optional
# leading series letter) + optional kind code. Matches "CN 121094816 A",
# "US 2023/0081319 A1", "TW I854998 B".
_PDF_PUBNO_RE = _re_fig.compile(
    r"\b([A-Z]{2})[\s/]{0,2}([A-Z]?\d[\d\s/,]{3,}\d)\s*([A-Z]\d?)?",
)


def _pubno_digit_core(s: str) -> str:
    """Digit core of a publication number: strip country prefix + kind suffix.

    "CN120543023A" -> "120543023", "US20230081319A1" -> "20230081319",
    "TWI854998B" -> "854998". Mirrors the GPSS neighbour-guard _req_core so the
    two identity guards stay consistent.
    """
    import re
    t = re.sub(r"^[A-Za-z]+", "", (s or "").strip())
    m = re.search(r"\d+", t)
    return m.group(0) if m else ""


# Alias used by the gpss3 headless scrapers so the row-selection guard and the
# PDF identity guard share one digit-core definition.
def _gpss_pubno_digit_core(s: str) -> str:
    return _pubno_digit_core(s)


def _gpss_extract_info(html: str) -> str:
    """Extract the GPSS INFO session token. gpss3 emits it UNQUOTED
    (`name=INFO value=005B83E9...`); gpss2 used quotes. Handles both orders."""
    import re
    m = re.search(r'name=["\']?INFO["\']?\s+value=["\']?([A-Za-z0-9]+)["\']?', html, re.IGNORECASE)
    if not m:
        m = re.search(r'value=["\']?([A-Za-z0-9]+)["\']?\s+name=["\']?INFO["\']?', html, re.IGNORECASE)
    return m.group(1) if m else ""


def _gpss_extract_action(html: str) -> str:
    """Extract the search-form action path. gpss3's action carries a
    `?@@<num>` query (`action="/gpss3/gpsskmc/gpssbkm?@@1032516905"`); the
    regex keeps the full path+query. Falls back to a bare gpss3 path."""
    import re
    m = re.search(r'action=["\']?(/gpss[123]?/gpsskmc/gpssbkm[^\'"\s>]*)["\']?', html, re.IGNORECASE)
    return m.group(1) if m else '/gpss3/gpsskmc/gpssbkm'


def _gpss_iter_result_rows(html: str):
    """Yield (harder_path, doc_type, embedded_pubno_core) for each
    result-list row's harder() document anchor.

    gpss3 list row anchors look like:
      onclick="harder(this,'/gpss3/gpsskmc/gpssbkm?<HEX>^CN_AN_CN120543023A_A_^<HEX2>^XX59_698645','pdf', ...)"
    The harder path embeds that row's pubno (`_CN120543023A_`), which is the
    reliable per-row identity (the visible row order is NOT). The figure detail
    entry (row PN anchor) is resolved separately by _gpss_select_detail_link —
    it is NOT part of this tuple (BR_20260706: a phantom 4th element here made
    the consumer's 4-way unpack crash on every non-empty result list).
    """
    import re
    for m in re.finditer(r"harder\(this,'([^']+)','([^']+)'", html):
        path, doc_type = m.group(1), m.group(2)
        mp = re.search(r'\^[A-Z]{2}_[A-Z]+_([A-Z]{2})(\d+)[A-Z]?_', path)
        core = mp.group(2) if mp else ""
        yield path, doc_type, core


def _gpss_select_detail_link(html: str, requested: str) -> str:
    """Return the matched row's PN link02 href (figure detail entry) for the
    requested pubno, or "" when no row's PN anchor core matches.

    This is the misresolve fix: select by digit-core, never by row position.
    The robust per-row identity is the PN link02 anchor's OWN visible text
    (e.g. `>CN<font>120543023</font>A</a>`), whose digit core is compared to the
    request — harder()/distance heuristics are unreliable across gpss3 rows.
    """
    import re
    req_core = _gpss_pubno_digit_core(requested)
    if not req_core:
        return ""
    # PN anchors carry the pubno as anchor text; the row-number link02 anchors
    # carry only a 1-2 digit row index, so a full digit-core compare ignores them.
    for m in re.finditer(
        r'href=["\']?(/gpss[123]?/gpsskmc/gpssbkm\?[^\s\'">]+)["\']?[^>]*class=["\']?link02[^>]*>(.*?)</a>',
        html, re.IGNORECASE | re.DOTALL,
    ):
        href, txt = m.group(1), m.group(2)
        digits = "".join(re.findall(r"\d", re.sub(r"<[^>]+>", "", txt)))
        if digits == req_core:
            return href
    return ""


def _gpss_select_harder_path(html: str, requested: str, prefer_types=None) -> str:
    """Return the matched row's harder() document path for the requested pubno.

    prefer_types: optional iterable of doc_type substrings to prefer (e.g.
    {"pdf"} for PDF, {"GX","XML"} for full-text XML). When given, only a row
    whose core matches AND whose doc_type matches a preferred token is returned.
    Returns "" when no matching row exists (misresolve-safe).
    """
    req_core = _gpss_pubno_digit_core(requested)
    if not req_core:
        return ""
    fallback = ""
    for path, doc_type, core in _gpss_iter_result_rows(html):
        if core != req_core:
            continue
        if prefer_types is None:
            return path
        if any(t.lower() in doc_type.lower() for t in prefer_types):
            return path
        fallback = fallback or path
    return fallback if prefer_types is not None else ""


def _detect_pdf_pubno_cores(pdf_path: str, max_pages: int = 5) -> List[str]:
    """Collect candidate publication-number digit cores from a PDF text layer.

    Scans the first `max_pages` pages (cover + opening spec pages carry the
    document's own publication number in the header/footer). Returns the
    DISTINCT digit cores (length >= 5) found, order-preserving. Empty list when
    the PDF has no usable text layer (scanned image) — the caller treats that as
    INCONCLUSIVE, never as a mismatch.
    """
    import re
    pages = _pdf_page_count(pdf_path)
    if pages <= 0:
        return []
    cores: List[str] = []
    seen = set()
    for p in range(1, min(max_pages, pages) + 1):
        text = _pdf_page_text(pdf_path, p)
        if not text.strip():
            continue
        for m in _PDF_PUBNO_RE.finditer(text):
            digits = re.sub(r"\D", "", m.group(2))
            if len(digits) >= 5 and digits not in seen:
                seen.add(digits)
                cores.append(digits)
    return cores


def _verify_pdf_identity(pdf_path: str, requested: str) -> Dict[str, Any]:
    """Verify a PDF really is the requested patent (BR_20260629).

    Returns {verified, requested_core, detected_cores, reason}:
      verified=True  — requested core found among the PDF's own pubno tokens.
      verified=False — pubno tokens detected but NONE match the requested core
                       (WRONG patent: a fuzzy neighbour or a wrong fallback).
      verified=None  — no pubno token detected (no text layer / unreadable);
                       INCONCLUSIVE — the caller may proceed but must NOT claim
                       the identity is verified.
    """
    requested_core = _pubno_digit_core(requested)
    detected = _detect_pdf_pubno_cores(pdf_path)
    if not requested_core:
        return {"verified": None, "requested_core": requested_core,
                "detected_cores": detected, "reason": "no requested core"}
    if not detected:
        return {"verified": None, "requested_core": requested_core,
                "detected_cores": detected, "reason": "no pubno in text layer"}
    if requested_core in detected:
        return {"verified": True, "requested_core": requested_core,
                "detected_cores": detected, "reason": "match"}
    return {"verified": False, "requested_core": requested_core,
            "detected_cores": detected,
            "reason": "no detected core matches requested"}


@mcp.tool()
async def extract_representative_figure(
    publication_number: Optional[str] = None,
    dpi: int = 200,
    patent_number: Optional[str] = None,
) -> Dict[str, Any]:
    """Extract a patent's representative figure as a high-resolution PNG (BR_20260628 D).

    Replaces the failed "pick the biggest object" heuristic (which selected
    full-page OCR text scans on scanned PDFs). Pipeline:
      1. Obtain the patent PDF via fetch_patent_pdf (epo_images / gpss_pdf /
         google_citation, with EPO single-page biblio downgrade).
      2. Locate the first FIG. 1 page with pdftotext (skips the cover page);
         falls back to highest reference-numeral density page.
      3. Render that page at `dpi` (default 200) with pdftoppm.

    Returns a docxmcp-style handle {token, rel, download_url, bytes, sha256}
    plus page_number / dpi / locate_method. On failure returns an EXPLICIT error
    (NO_PDF / NO_FIGURE_PAGE / RENDER_FAILED) — it never inserts a wrong page.

    Use this for report-grade figures; NEVER use representative_figure_url
    thumbnails (60x80 index images) for deliverables.

    `patent_number` is a backward-compatible alias for `publication_number`.

    [LANDED → skills/patentworks/scripts/figure_extract.py]

    R13 compute/landing split: the PDF→FIG.1→PNG pipeline is a deterministic
    poppler-CLI post-process. Fetch the PDF in-container via `fetch_patent_pdf`
    (network stays here), download it, then run the landing script locally
    (poppler on host; it precheck-fails with MISSING_DEPENDENCY if absent).
    Returns a TOOL_LANDED redirect envelope.
    """
    return {
        "success": False,
        "error_code": "TOOL_LANDED",
        "landing": {
            "script": "skills/patentworks/scripts/figure_extract.py",
            "usage": (
                "# 1) fetch_patent_pdf(publication_number) → download the PDF locally\n"
                "python3 skills/patentworks/scripts/figure_extract.py "
                "--pdf patent.pdf --out figure.png --dpi 200"
            ),
        },
    }


@mcp.tool()
async def gpss_download_representative_figure(
    publication_number: str,
    all_figures: bool = False,
) -> Dict[str, Any]:
    """Download a patent's figure(s) from the TIPO GPSS detail page (COUNTRY-AGNOSTIC).

    Works for ANY jurisdiction (US/CN/TW/EP/WO/…). The GPSS detail page exposes
    two figure families per patent — a low-res representative thumbnail (<C>G1)
    and the full 圖式(A1) series (<C>G2_<NNN>, ~600px, _000 = FIG.1). This tool
    prefers the full-resolution G2 page for the representative figure.

    all_figures=False (default): returns ONE handle {token, rel, download_url,
      bytes, sha256, figure_kind, full_figures_available} of the representative
      figure (full-res G2 _000 when available).
    all_figures=True: returns {representative, figures:[...], figure_count} where
      figures is the whole full-res G2 全部圖式(A1) series — the same set a human
      sees via the detail page's 影像 → 全部圖式(A1) menu.

    BR_20260628 A: serialized through _GPSS_POLICY (Concurrency=1 + random
    pacing + cooldown parking), so parallel calls cannot trip Cloudflare's
    Managed Challenge on tiponet.tipo.gov.tw.
    """
    async with _GPSS_POLICY.guard():
        return await _gpss_download_representative_figure_impl(
            publication_number, all_figures=all_figures
        )


async def _gpss_download_representative_figure_impl(
    publication_number: str,
    session_client=None,
    all_figures: bool = False,
) -> Dict[str, Any]:
    """Scrape one patent's figure(s) from the GPSS detail page (COUNTRY-AGNOSTIC).
    NO lock here — the caller (the tool wrapper or _GpssScrapeSession.fetch_*)
    owns _GPSS_SCRAPE_LOCK + pacing.

    session_client: when provided, reuse this persistent client (cookie jar /
    cf_clearance continuity across a batch); when None, a throwaway client is
    created and closed for this single scrape.
    all_figures: when False (default) download only the representative figure
    (prefers the full-res G2 _000 page); when True download the whole
    G2 全部圖式(A1) series.
    """
    import re

    pat = publication_number.strip()
    
    try:
        async with _gpss_client(session_client) as client:
            # Step 1: Visit portal
            await client.get("https://tiponet.tipo.gov.tw/030_OUT_V1/home.do")
            
            # Step 2: Initialize GPSS session (gpss3 = 113/11/29 域整併現役介面)
            await client.get("https://tiponet.tipo.gov.tw/gpss3/")
            
            # Step 3: Load search page and bypass client-side JS random redirect
            rand_val = random.random()
            gpss_url = f"https://tiponet.tipo.gov.tw/gpss3/gpsskmc/gpssbkm?@@{rand_val}"
            res = await client.get(gpss_url)
            
            info_val = _gpss_extract_info(res.text)
            if not info_val:
                return {"success": False, "error": "Failed to retrieve INFO token from GPSS session"}
            
            action_url = f"https://tiponet.tipo.gov.tw{_gpss_extract_action(res.text)}"
            
            # Step 4: Search POST
            data = {
                "INFO": info_val,
                "@_21_1_T": "T_XX",
                "_21_1_T": pat,
                "@_0_9_T": "T_XX",
                "_0_9_T": "",
                "_IMG_檢索.x": "25",
                "_IMG_檢索.y": "25"
            }
            res = await client.post(action_url, data=data)
            
            # Handle refresh redirect if any
            m_refresh = re.search(r'CONTENT=["\']?0;\s*URL=([^"\'>\s]+)["\']?', res.text, re.IGNORECASE)
            if m_refresh:
                redirect_url = m_refresh.group(1).strip("'\"")
                if not redirect_url.startswith("http"):
                    redirect_url = f"https://tiponet.tipo.gov.tw/gpss3/gpsskmc/{redirect_url}"
                res = await client.get(redirect_url)
            
            # Step 5: Pick the detail link for the REQUESTED pubno (misresolve fix).
            # gpss3 returns a MULTI-ROW list; the legacy "first class=link02" logic
            # landed on the neighbour row (CN120543023A request -> row 1
            # CN121094816A). Select the row whose harder() path embeds a pubno
            # digit-core == the requested digit-core, and follow THAT row's PN
            # link02 anchor (the figure detail page entry).
            detail_path = _gpss_select_detail_link(res.text, pat)
            if not detail_path:
                return {
                    "success": False,
                    "error": (
                        "GPSS result list has no row matching the requested patent "
                        "— refusing to fall back to a neighbour row."
                    ),
                    "requested": pat,
                    "requested_number_core": _gpss_pubno_digit_core(pat),
                }
                
            detail_url = f"https://tiponet.tipo.gov.tw{detail_path}"
            res_detail = await client.get(detail_url)
            
            # Extract image URLs (COUNTRY-AGNOSTIC). The GPSS detail page exposes
            # two figure families for EVERY jurisdiction (US/CN/TW/EP/WO/…), the
            # country prefix only changes the leading code:
            #   <C>G1<NO>.png          -> representative THUMBNAIL (~300px, low-res)
            #   <C>G2<NO>_<NNN>.png    -> FULL 圖式(A1) series (~600px), _000 = FIG.1
            # The old code hardcoded "TWG1", so any non-TW patent never matched and
            # fell through to img_urls[0] (whatever came first) AND never touched the
            # high-res G2 series — that is why US/CN cases came back as a blurry
            # thumbnail or "no figure". This handles all jurisdictions and prefers
            # the full-resolution G2 pages (what the human sees via 影像→全部圖式(A1)).
            # Image extension is jurisdiction-dependent (US/TW = .png, CN = .jpg, …),
            # so match any common raster extension, not a hardcoded .png.
            raw = re.findall(
                r'/gpss\d?/gpssbkmusr/[^\'" >]+\.(?:png|jpe?g|gif|tiff?)',
                res_detail.text, re.IGNORECASE,
            )
            seen = set()
            img_urls = []
            for u in raw:
                base = u.split("?", 1)[0]  # strip cache-buster querystring
                if base not in seen:
                    seen.add(base)
                    img_urls.append(base)

            def _is_g2(u):
                return re.search(r'G2[^/]*_\d+\.(?:png|jpe?g|gif|tiff?)$', u, re.IGNORECASE) is not None

            def _is_g1(u):
                return re.search(r'G1[^/]*\.(?:png|jpe?g|gif|tiff?)$', u, re.IGNORECASE) is not None

            g2_series = sorted(u for u in img_urls if _is_g2(u))
            g1_thumbs = [u for u in img_urls if _is_g1(u)]

            # GUARD against silently returning a NEIGHBOUR patent's figure.
            # The GPSS headless search POST is fuzzy: when the requested patent's
            # images are not yet in the GPSS image库 (e.g. a very recent
            # publication), the search can land on an adjacent result and the
            # detail page — and ALL its figure URLs — belong to a DIFFERENT
            # patent. The figure filename embeds the publication number
            # (<C>G2<NUMBER>_<NNN>), so compare its digit core to the requested
            # number; on mismatch fail LOUD instead of handing back the wrong
            # patent's drawing.
            def _req_core(s):
                # Requested pubno: strip country prefix + kind suffix, keep the
                # digit core. "CN120543023A" -> "120543023", "US20230081319A1"
                # -> "20230081319", "TWI854998B" -> "854998".
                t = re.sub(r"^[A-Za-z]+", "", (s or "").strip())
                m = re.search(r"\d+", t)
                return m.group(0) if m else ""

            def _fig_core(fname):
                # Figure filename embeds the number AFTER the G1/G2 marker:
                # "CNG2120672280A_000.jpg" -> "120672280",
                # "USG220230081319A1_000.png" -> "20230081319",
                # "TWG1202503567A.png" -> "202503567". Strip everything up to and
                # including G1/G2 so the marker's own digit ("2") is not glued on.
                m = re.search(r"G[12](\d+)", fname, re.IGNORECASE)
                return m.group(1) if m else ""

            req_core = _req_core(pat)
            all_candidates = g2_series + g1_thumbs + img_urls
            if req_core and all_candidates:
                got_core = _fig_core(all_candidates[0].rsplit("/", 1)[-1])
                if got_core and got_core != req_core:
                    return {
                        "success": False,
                        "error": (
                            "GPSS detail page resolved to a DIFFERENT patent — "
                            "the requested patent's figures are not in the GPSS "
                            "image库 (often a very recent publication). Refusing "
                            "to return a neighbour's figure."
                        ),
                        "requested": pat,
                        "resolved_figure": all_candidates[0].rsplit("/", 1)[-1],
                        "requested_number_core": req_core,
                        "resolved_number_core": got_core,
                    }

            async def _grab(rel_url):
                r = await client.get(f"https://tiponet.tipo.gov.tw{rel_url}")
                if r.status_code != 200:
                    return None
                return token_store.put_bytes(r.content, rel_url.rsplit("/", 1)[-1])

            # Representative: prefer full-res G2 _000, else G1 thumb, else first image.
            rep_url = (g2_series[0] if g2_series
                       else (g1_thumbs[0] if g1_thumbs
                             else (img_urls[0] if img_urls else None)))
            if not rep_url:
                return {"success": False, "error": "No figure found on the GPSS detail page for this patent"}

            rep_entry = await _grab(rep_url)
            if rep_entry is None:
                return {"success": False, "error": "Failed to download representative figure"}
            rep_handle = _handle(rep_entry)
            rep_handle["figure_kind"] = "full_g2" if _is_g2(rep_url) else ("thumb_g1" if _is_g1(rep_url) else "unknown")
            rep_handle["full_figures_available"] = len(g2_series)

            if not all_figures:
                return rep_handle

            # all_figures=True: download the whole G2 全部圖式(A1) series (full-res).
            figures = []
            for u in g2_series:
                ent = await _grab(u)
                if ent is not None:
                    figures.append(_handle(ent))
            return {
                "success": True,
                "representative": rep_handle,
                "figures": figures,
                "figure_count": len(figures),
                "source": "gpss_g2_full_figures",
            }
            
    except Exception as e:
        return {"success": False, "error": f"GPSS figure download exception: {str(e)}"}


@mcp.tool()
async def gpss_download_patent_pdf(
    publication_number: str,
) -> Dict[str, Any]:
    """Download a patent's original PDF headlessly from TIPO GPSS into the token store.

    This replicates a browser session to fetch the patent's PDF document.
    Returns a handle {token, rel, download_url, bytes, sha256} of the saved PDF.

    BR_20260628 A: serialized through _GPSS_POLICY (Concurrency=1 + random
    pacing + cooldown parking). The local-cache fast path also runs under the
    guard; this is cheap and keeps the single-thread guarantee simple and total.
    """
    async with _GPSS_POLICY.guard():
        return await _gpss_download_patent_pdf_impl(publication_number)


async def _gpss_download_patent_pdf_impl(
    publication_number: str,
    session_client=None,
) -> Dict[str, Any]:
    """Scrape one TW patent PDF. NO lock here — the caller owns _GPSS_SCRAPE_LOCK
    + pacing. session_client: reuse a persistent client when provided (batch
    cookie continuity), else a throwaway client is created/closed per call."""
    import re

    pat = publication_number.strip()
    # Remove all whitespace
    pat = re.sub(r'\s+', '', pat)
    # Remove country prefix
    pat = re.sub(r'^(?:TW|tw)', '', pat)
    # Remove trailing kind codes for TW patents:
    # 1. Certificate numbers like I123456B -> I123456, M123456U -> M123456, D123456 -> D123456
    m_cert = re.match(r'^([IMD]\d+)[A-Za-z]*$', pat, re.IGNORECASE)
    if m_cert:
        pat = m_cert.group(1).upper()
    else:
        # 2. Application/Publication numbers like 202412345A -> 202412345, 112123456 -> 112123456
        m_app = re.match(r'^(\d+)[A-Za-z]*$', pat)
        if m_app:
            pat = m_app.group(1)

    # Local Cache Priority Check
    country, norm_pat = _get_patent_country_and_normalized_no(publication_number)
    cache_path = _find_local_patent_cache(country, norm_pat, "pdf")
    if cache_path:
        logger.info(f"Local cache HIT for GPSS PDF: {country}/{norm_pat}")
        filename = f"{norm_pat}_specification.pdf"
        entry = token_store.put_bytes(cache_path.read_bytes(), filename)
        return _handle(entry)

    try:
        async with _gpss_client(session_client) as client:
            # Step 1: Visit portal
            await client.get("https://tiponet.tipo.gov.tw/030_OUT_V1/home.do")
            
            # Step 2: Initialize GPSS session (gpss3 = 113/11/29 域整併現役介面)
            await client.get("https://tiponet.tipo.gov.tw/gpss3/")
            
            # Step 3: Load search page and bypass client-side JS random redirect
            rand_val = random.random()
            gpss_url = f"https://tiponet.tipo.gov.tw/gpss3/gpsskmc/gpssbkm?@@{rand_val}"
            res = await client.get(gpss_url)
            
            info_val = _gpss_extract_info(res.text)
            if not info_val:
                return {"success": False, "error": "Failed to retrieve INFO token from GPSS session"}
            
            action_url = f"https://tiponet.tipo.gov.tw{_gpss_extract_action(res.text)}"
            
            # Step 4: Search POST
            data = {
                "INFO": info_val,
                "@_21_1_T": "T_XX",
                "_21_1_T": pat,
                "@_0_9_T": "T_XX",
                "_0_9_T": "",
                "_IMG_檢索.x": "25",
                "_IMG_檢索.y": "25"
            }
            res = await client.post(action_url, data=data)
            
            # Handle refresh redirect if any
            m_refresh = re.search(r'CONTENT=["\']?0;\s*URL=([^"\'>\s]+)["\']?', res.text, re.IGNORECASE)
            if m_refresh:
                redirect_url = m_refresh.group(1).strip("'\"")
                if not redirect_url.startswith("http"):
                    redirect_url = f"https://tiponet.tipo.gov.tw/gpss3/gpsskmc/{redirect_url}"
                res = await client.get(redirect_url)
            
            # Step 5+6: Pick the PDF harder() document path for the REQUESTED pubno
            # (misresolve fix). gpss3 returns a MULTI-ROW list and each row's
            # harder() path embeds that row's pubno; select by digit-core match
            # instead of taking the first row's link. The matched harder('pdf')
            # GET returns a ~153B Refresh page -> URL=.../CNA-<pubno>A.pdf.
            selected_path = _gpss_select_harder_path(res.text, pat, prefer_types={"pdf"})
            if not selected_path:
                return {
                    "success": False,
                    "error": (
                        "No PDF document row matching the requested patent in the "
                        "GPSS result list — refusing to fall back to a neighbour row."
                    ),
                    "requested": pat,
                    "requested_number_core": _gpss_pubno_digit_core(pat),
                }
                
            # Step 7: Request the intermediate HTML page for the selected PDF
            pdf_page_url = f"https://tiponet.tipo.gov.tw{selected_path}"
            res_pdf_page = await client.get(pdf_page_url)
            
            # Extract the actual PDF file path from this HTML page
            m_pdf = re.search(r'/gpss[123]?/gpssbkmusr/[^\'" >]+\.pdf', res_pdf_page.text, re.IGNORECASE)
            if not m_pdf:
                return {"success": False, "error": "Failed to parse the actual PDF binary path from the GPSS document page"}
                
            actual_pdf_url = f"https://tiponet.tipo.gov.tw{m_pdf.group(0)}"
            
            # Step 8: Download actual PDF bytes
            pdf_res = await client.get(actual_pdf_url)
            if pdf_res.status_code != 200:
                return {"success": False, "error": f"Failed to download GPSS PDF (HTTP {pdf_res.status_code})"}
                
            if not pdf_res.content.startswith(b"%PDF"):
                return {"success": False, "error": "Downloaded content is not a valid PDF"}
                
            # Save to Local Cache (Write-Through)
            _save_local_patent_cache(country, norm_pat, "pdf", pdf_res.content)

            # Put bytes to token store
            filename = actual_pdf_url.rsplit("/", 1)[-1] or f"{pat}_specification.pdf"
            entry = token_store.put_bytes(pdf_res.content, filename)
            return _handle(entry)
            
    except Exception as e:
        return {"success": False, "error": f"GPSS PDF download exception: {str(e)}"}


@mcp.tool()
async def gpss_download_patent_xml(
    publication_number: str,
) -> Dict[str, Any]:
    """Download a patent's structured XML specification headlessly from TIPO GPSS into the token store.

    This replicates a browser session to fetch the patent's full-text XML document (best for TW patents).
    Returns a handle {token, rel, download_url, bytes, sha256} of the saved XML.

    BR_20260628 A: serialized through _GPSS_POLICY (Concurrency=1 + random
    pacing + cooldown parking), sharing the single guardrail with the figure/pdf
    tools.
    """
    async with _GPSS_POLICY.guard():
        return await _gpss_download_patent_xml_impl(publication_number)


async def _gpss_download_patent_xml_impl(
    publication_number: str,
    session_client=None,
) -> Dict[str, Any]:
    """Scrape one TW patent XML. NO lock here — the caller owns _GPSS_POLICY.guard.
    session_client: reuse a persistent client when provided (batch cookie
    continuity), else a throwaway client is created/closed per call."""
    import re

    pat = publication_number.strip()
    # Remove all whitespace
    pat = re.sub(r'\s+', '', pat)
    # Remove country prefix
    pat = re.sub(r'^(?:TW|tw)', '', pat)
    # Remove trailing kind codes for TW patents:
    m_cert = re.match(r'^([IMD]\d+)[A-Za-z]*$', pat, re.IGNORECASE)
    if m_cert:
        pat = m_cert.group(1).upper()
    else:
        m_app = re.match(r'^(\d+)[A-Za-z]*$', pat)
        if m_app:
            pat = m_app.group(1)

    # Local Cache Priority Check
    country, norm_pat = _get_patent_country_and_normalized_no(publication_number)
    cache_path = _find_local_patent_cache(country, norm_pat, "xml")
    if cache_path:
        logger.info(f"Local cache HIT for GPSS XML: {country}/{norm_pat}")
        filename = f"{norm_pat}_specification.xml"
        entry = token_store.put_bytes(cache_path.read_bytes(), filename)
        return _handle(entry)

    try:
        async with _gpss_client(session_client) as client:
            # Step 1: Visit portal
            await client.get("https://tiponet.tipo.gov.tw/030_OUT_V1/home.do")
            
            # Step 2: Initialize GPSS session (gpss3 = 113/11/29 域整併現役介面)
            await client.get("https://tiponet.tipo.gov.tw/gpss3/")
            
            # Step 3: Load search page and bypass client-side JS random redirect
            rand_val = random.random()
            gpss_url = f"https://tiponet.tipo.gov.tw/gpss3/gpsskmc/gpssbkm?@@{rand_val}"
            res = await client.get(gpss_url)
            
            info_val = _gpss_extract_info(res.text)
            if not info_val:
                return {"success": False, "error": "Failed to retrieve INFO token from GPSS session"}
            
            action_url = f"https://tiponet.tipo.gov.tw{_gpss_extract_action(res.text)}"
            
            # Step 4: Search POST
            data = {
                "INFO": info_val,
                "@_21_1_T": "T_XX",
                "_21_1_T": pat,
                "@_0_9_T": "T_XX",
                "_0_9_T": "",
                "_IMG_檢索.x": "25",
                "_IMG_檢索.y": "25"
            }
            res = await client.post(action_url, data=data)
            
            # Handle refresh redirect if any
            m_refresh = re.search(r'CONTENT=["\']?0;\s*URL=([^"\'>\s]+)["\']?', res.text, re.IGNORECASE)
            if m_refresh:
                redirect_url = m_refresh.group(1).strip("'\"")
                if not redirect_url.startswith("http"):
                    redirect_url = f"https://tiponet.tipo.gov.tw/gpss3/gpsskmc/{redirect_url}"
                res = await client.get(redirect_url)
            
            # Step 5+6: Pick the Full-text XML (TW_GX) harder() document path for
            # the REQUESTED pubno (misresolve fix). gpss3 returns a MULTI-ROW list
            # and each row's harder() path embeds that row's pubno; select by
            # digit-core match + an XML/GX doc-type, never by row position. Only TW
            # full-text rows expose a GX/XML harder type — foreign-language rows
            # (CN/US/…) only carry 'pdf', so absence is reported explicitly.
            selected_path = _gpss_select_harder_path(
                res.text, pat, prefer_types={"TW_GX", "_GX", "xml"}
            )
            if not selected_path:
                return {
                    "success": False,
                    "error": (
                        f"TW_GX (Full-text XML) download row for '{pat}' not found in "
                        "the GPSS result list (only TW full-text patents expose XML)."
                    ),
                    "requested": pat,
                    "requested_number_core": _gpss_pubno_digit_core(pat),
                }
                
            # Step 7: Request the intermediate HTML page for the selected document
            xml_page_url = f"https://tiponet.tipo.gov.tw{selected_path}"
            res_xml_page = await client.get(xml_page_url)
            
            # Extract the actual dc.xml file path from this Refresh HTML page
            m_xml = re.search(r'CONTENT=["\']?0;\s*URL=[\'"]?([^\'">\s]+)[\'"]?', res_xml_page.text, re.IGNORECASE)
            if not m_xml:
                return {"success": False, "error": "Failed to parse the actual XML path from the GPSS full-text page"}
                
            actual_xml_url = f"https://tiponet.tipo.gov.tw{m_xml.group(1)}"
            
            # Step 8: Download actual XML bytes
            xml_res = await client.get(actual_xml_url)
            if xml_res.status_code != 200:
                return {"success": False, "error": f"Failed to download GPSS XML (HTTP {xml_res.status_code})"}
                
            content = xml_res.content
            # Check if valid XML structure (allow UTF-8 BOM)
            if not (content.startswith(b"<?xml") or content.startswith(b"\xef\xbb\xbf<?xml")):
                return {"success": False, "error": "Downloaded content is not a valid XML specification document"}
                
            # Save to Local Cache (Write-Through)
            _save_local_patent_cache(country, norm_pat, "xml", content)

            # Put bytes to token store
            filename = actual_xml_url.rsplit("/", 1)[-1].split("?")[0] or f"{pat}_specification.xml"
            entry = token_store.put_bytes(content, filename)
            return _handle(entry)
            
    except Exception as e:
        return {"success": False, "error": f"GPSS XML download exception: {str(e)}"}


@mcp.tool()
async def fetch_patent_pdf(
    publication_number: Optional[str] = None,
    sources: Optional[List[str]] = None,
    filename: Optional[str] = None,
    include_attempts: bool = False,
    allow_scraping: bool = False,
    patent_number: Optional[str] = None,
) -> Dict[str, Any]:
    """Fetch a patent's original PDF for a KNOWN publication number.

    Routes official sources first, then the Google Patents citation fallback:
      1. epo_images     — EPO OPS official image API (OAuth, no scraping).
                          Best for EP/WO and many national members.
      2. gpss_pdf       — simulated TIPO GPSS session to fetch the original
                          patent PDF (best for TW patents).
      3. google_citation — resolve the true hashed `citation_pdf_url` from the
                          patent's Google Patents page, then download. This is a
                          SINGLE known-number page resolution (NOT batch
                          scraping); use as last resort.

    The PDF bytes are LANDED in the token store and returned as a docxmcp-style
    handle {token, rel, download_url, bytes, sha256}; bytes never flow through
    the model context. Hand the token to docxmcp's PDF decompose to extract the
    original figures.

    sources: attempt order; defaults to ["epo_images", "gpss_pdf", "google_citation"].
    include_attempts: attach a per-source attempts[] trace to the result.
    allow_scraping: EXPLICIT gate for the scraping source. The `gpss_pdf` source
        runs a TIPO GPSS headless session (provenance scraping=True). When
        allow_scraping is False (the default), gpss_pdf is SKIPPED — recorded in
        attempts as {"ok": False, "error": "SKIPPED_SCRAPING_NOT_AUTHORIZED"}
        without any actual fetch. If every official source (epo_images /
        google_citation / local_cache) misses and the only remaining candidate
        was the skipped gpss_pdf, the call returns {"success": False,
        "error": "SCRAPING_REQUIRED", ...} so the caller must opt in explicitly.
        Set allow_scraping=True only with user authorization (e.g. TW figure
        extraction). This is a fail-fast gate, NOT a silent fallback.
    patent_number: backward-compatible alias for `publication_number`.
    """
    pub = publication_number or patent_number
    if not pub:
        return {"success": False, "error": "MISSING_PUBLICATION_NUMBER",
                "detail": "publication_number (or patent_number alias) is required"}
    publication_number = pub
    order = sources or ["epo_images", "gpss_pdf", "google_citation"]
    attempts: List[Dict[str, Any]] = []
    name = filename or f"{publication_number}.pdf"
    scraping_skipped = False

    # Global Local Cache Priority Check (Read-Through)
    country, norm_pat = _get_patent_country_and_normalized_no(publication_number)
    cache_path = _find_local_patent_cache(country, norm_pat, "pdf")
    if cache_path:
        logger.info(f"Local cache HIT for fetch_patent_pdf: {country}/{norm_pat}")
        entry = token_store.put_bytes(cache_path.read_bytes(), name)
        result = _handle(entry)
        result["source"] = "local_cache"
        result["provenance"] = {"path": str(cache_path), "scraping": False}
        return result

    for src in order:
        if src == "epo_images":
            if not epo_client.configured():
                attempts.append({"source": src, "ok": False, "error": "EPO_NOT_CONFIGURED"})
                continue
            try:
                meta = await epo_client.images(publication_number)
                if not meta.get("success"):
                    attempts.append({"source": src, "ok": False,
                                     "error": meta.get("error", "images lookup failed")})
                    continue
                if meta.get("count") == 0:
                    attempts.append({"source": src, "ok": False, "error": "NO_IMAGES"})
                    continue
                data = await epo_client.download_image_pdf(publication_number)
                if not data:
                    attempts.append({"source": src, "ok": False, "error": "EMPTY_PDF"})
                    continue

                # BR_20260628 F: EPO OPS only serves biblio (cover) pages for many
                # CN/TW patents — a 1-page PDF with no specification figures. Never
                # land such a PDF as a figure source; downgrade to the next source.
                epo_pages = _pdf_bytes_page_count(data)
                if epo_pages <= 1:
                    attempts.append({"source": src, "ok": False,
                                     "error": "EPO_BIBLIO_ONLY_1PAGE", "pages": epo_pages})
                    continue

                # Save to Local Cache (Write-Through)
                _save_local_patent_cache(country, norm_pat, "pdf", data)

                entry = token_store.put_bytes(data, name)
                result = _handle(entry)
                result["source"] = src
                result["provenance"] = {"api": "EPO OPS published-data/images",
                                        "scraping": False, "pages": epo_pages}
                attempts.append({"source": src, "ok": True, "bytes": entry.size_bytes})
                if include_attempts:
                    result["attempts"] = attempts
                return result
            except Exception as e:  # noqa: BLE001
                attempts.append({"source": src, "ok": False, "error": str(e)})
                continue

        elif src == "gpss_pdf":
            if not allow_scraping:
                scraping_skipped = True
                attempts.append({"source": src, "ok": False,
                                 "error": "SKIPPED_SCRAPING_NOT_AUTHORIZED"})
                continue
            try:
                res_gpss = await gpss_download_patent_pdf(publication_number)
                if res_gpss.get("success"):
                    # BR_20260629: GPSS headless search is fuzzy — it can land on
                    # a NEIGHBOUR patent and return the WRONG document. Verify the
                    # scraped PDF's own publication number before trusting it; a
                    # confirmed mismatch (verified is False) is a source FAILURE,
                    # NOT a silent fallback to the wrong patent.
                    try:
                        gpss_pdf_path = str(token_store.blob_path(
                            res_gpss["token"], res_gpss["rel"]))
                        ident = _verify_pdf_identity(gpss_pdf_path, publication_number)
                    except Exception:  # noqa: BLE001
                        ident = {"verified": None, "requested_core": "",
                                 "detected_cores": [], "reason": "verify error"}
                    if ident["verified"] is False:
                        attempts.append({
                            "source": src, "ok": False,
                            "error": "WRONG_PATENT_FETCHED",
                            "requested_number_core": ident["requested_core"],
                            "detected_number_cores": ident["detected_cores"]})
                        continue
                    res_gpss["source"] = src
                    res_gpss["provenance"] = {"api": "TIPO GPSS headless session",
                                              "scraping": True,
                                              "identity_verified": ident["verified"],
                                              "detected_number_cores": ident["detected_cores"]}
                    attempts.append({"source": src, "ok": True, "bytes": res_gpss.get("bytes")})
                    if include_attempts:
                        res_gpss["attempts"] = attempts
                    return res_gpss
                else:
                    attempts.append({"source": src, "ok": False,
                                     "error": res_gpss.get("error", "GPSS PDF download failed")})
                    continue
            except Exception as e:  # noqa: BLE001
                attempts.append({"source": src, "ok": False, "error": str(e)})
                continue

        elif src == "google_citation":
            try:
                resolved = await gpatents_client.resolve_pdf_url(publication_number)
                if not resolved.get("success"):
                    attempts.append({"source": src, "ok": False,
                                     "error": resolved.get("error", "resolve failed"),
                                     "http_code": resolved.get("http_code")})
                    continue
                pdf_url = resolved["pdf_url"]
                data = await gpatents_client.fetch_bytes(pdf_url)
                if not data:
                    attempts.append({"source": src, "ok": False, "error": "EMPTY_PDF"})
                    continue

                # Save to Local Cache (Write-Through)
                _save_local_patent_cache(country, norm_pat, "pdf", data)

                entry = token_store.put_bytes(data, name)
                result = _handle(entry)
                result["source"] = src
                result["provenance"] = {"resolved_pdf_url": pdf_url, "scraping": False,
                                        "note": "single known-number page resolution, not batch scraping"}
                attempts.append({"source": src, "ok": True, "bytes": entry.size_bytes})
                if include_attempts:
                    result["attempts"] = attempts
                return result
            except Exception as e:  # noqa: BLE001
                attempts.append({"source": src, "ok": False, "error": str(e)})
                continue

        else:
            attempts.append({"source": src, "ok": False, "error": "UNKNOWN_SOURCE"})

    if scraping_skipped:
        return {"success": False, "error": "SCRAPING_REQUIRED",
                "publication_number": publication_number, "attempts": attempts,
                "hint": "官方來源無此 PDF;GPSS headless 抓取需 allow_scraping=True 並取得使用者授權"}
    return {"success": False, "error": "ALL_SOURCES_FAILED",
            "publication_number": publication_number, "attempts": attempts}


# =====================================================================
# TIPO GPSS Tool — official REST API, CPC/IPC + claims search (US/CN)
# =====================================================================

async def _gpss_search_impl(
    cpc: Optional[str] = None,
    ipc: Optional[str] = None,
    keyword: Optional[str] = None,
    keyword_field: Optional[str] = "TI/AB",
    inventor_country: Optional[str] = None,
    applicant: Optional[str] = None,
    pub_number: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    databases: Optional[List[str]] = None,
    patent_type: Optional[str] = None,
    case_type: Optional[str] = None,
    fields: Optional[str] = None,
    num: Optional[int] = 30,
    skip: Optional[int] = 0,
) -> Dict[str, Any]:
    """Search patents via TIPO GPSS (official REST API). Preferred source when a
    GPSS_USER_CODE is configured: ToS-clean, quota-billed (not bytes-scanned),
    supports CPC/IPC anchoring and full-text CLAIMS search, returns JSON.

    Per project rule, anchor searches on `cpc` (CPC class, e.g. "G10L25/51";
    combine with " AND "/" OR "). All given conditions are AND-combined.
    Defaults to US/CN databases (USA,USB,CNA,CNB); TW is low value, add it via
    `databases` only if needed.

    Args:
        cpc: CPC condition -> CS field (e.g. "G10L25/51", "H02J AND B60R").
        ipc: IPC condition -> IC field.
        keyword: free-text -> applied to `keyword_field`.
        keyword_field: one of TI, AB, CL, "TI/AB", "TI/AB/CL".
        inventor_country / applicant / pub_number: IY / AX / PN conditions.
        date_from/date_to: publication date bounds -> ID=from:to (YYYYMMDD).
        databases: patDB list (default USA,USB,CNA,CNB).
        patent_type: patTY, e.g. "I,M" (發明/新型); case_type: patAG "A,B".
        fields: expFld override (default PN,ID,TI,IN,PA,AB,CS,CL).
        num/skip: expQty / expSkip pagination.

    Returns the parsed GPSS JSON plus success/status/message.
    """
    conditions: List[GPSSCondition] = []
    if cpc:
        conditions.append(GPSSCondition("CS", cpc))
    if ipc:
        conditions.append(GPSSCondition("IC", ipc))
    if keyword:
        conditions.append(GPSSCondition(keyword_field or "TI/AB", keyword))
    if inventor_country:
        conditions.append(GPSSCondition("IY", inventor_country))
    if applicant:
        conditions.append(GPSSCondition("AX", applicant))
    if pub_number:
        conditions.append(GPSSCondition("PN", pub_number))
    if date_from or date_to:
        conditions.append(GPSSCondition("ID", f"{date_from or ''}:{date_to or ''}"))

    res = await gpss_client.search(
        conditions=conditions,
        databases=databases,
        case_type=case_type,
        patent_type=patent_type,
        fields=fields or "PN,ID,TI,IN,PA,AB,CS,CL",
        num=num or 30,
        skip=skip or 0,
        fmt="json",
    )

    # BR_20260628 D: GPSS occasionally returns an empty/boilerplate-only Claim 1
    # for US cases ("What is claimed is:" with no body). The raw JSON gives no
    # signal, so a caller can silently hand off a blank claim. Surface a
    # non-invasive advisory (reusing gpss_to_records as the single source of the
    # claim1_empty rule) listing the pub numbers that need a PPUBS fallback —
    # without mutating the original GPSS payload structure.
    if isinstance(res, dict) and res.get("success"):
        try:
            recs = _st.gpss_to_records(res)
            empties = [r.get("pubno", "") for r in recs if r.get("claim1_empty")]
            res["claim1_audit"] = {
                "checked": len(recs),
                "empty_count": len(empties),
                "empty_pubnos": empties,
                "fallback": (
                    "Claim 1 為空/僅樣板的公開號需走 ppubs_batch_get_claims 補抓"
                    if empties else None
                ),
            }
        except Exception as e:  # noqa: BLE001 — advisory must never break search
            logger.warning("_gpss_search_impl claim1_audit failed: %s", e)

    return res


# =====================================================================
# EPO OPS Tools — official INPADOC family / biblio / CQL search
# =====================================================================

@mcp.tool(annotations=_RO)
async def epo_family(publication_number: str) -> Dict[str, Any]:
    """Get the INPADOC patent family for a publication via EPO OPS (official).

    Unifies the US/CN/TW/EP/JP members of one invention into a single family —
    more reliable than BigQuery's split family_id. Pass any member's number
    (e.g. "US11213256B2"); returns {family_id, count, members:[pub numbers]}.
    Use to deduplicate a screening pool by true family or to expand a seed.
    """
    return await epo_client.family(publication_number)


@mcp.tool()
async def patent_family_backfill(
    pubnos: Optional[List[str]] = None,
    from_pool_missing: bool = False,
    cursor: int = 0,
    max_calls: Optional[int] = None,
    time_budget_sec: float = 0,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """Backfill official INPADOC family_id into patentdb via EPO OPS — RUNS TO
    COMPLETION in a single call by default.

    epo_family is single-number; this orchestrates it over a list, throttles to
    EPO OPS 15/min, applies family-coverage (one call stamps the whole INPADOC
    family), and upserts family_id back into patentdb.sqlite. The batch loop is
    INTERNAL: one invocation sweeps the ENTIRE target set (exhausted=true) with
    no per-batch MCP round-trips. Only cap the run if you must:

    Args:
        pubnos: explicit publication numbers to backfill. Ignored if
            from_pool_missing=true.
        from_pool_missing: if true, ignore `pubnos` and pull the patentdb rows
            whose family_id is still NULL/empty (ordered by pubno for a stable
            cursor). Use this to sweep the whole DB.
        cursor: 0-based offset into the target list; pass the returned
            next_cursor to resume a partial run. Normally 0 (runs to the end).
        max_calls: OPTIONAL hard cap on EPO family calls this invocation.
            Default None = no cap (run to completion). Set only to bound cost.
        time_budget_sec: OPTIONAL wall-clock budget in seconds. Default 0 =
            unbounded (run to completion). If set >0, the loop stops when the
            elapsed time would exceed it and returns next_cursor for a resume;
            use this if a caller's transport imposes a hard timeout. With the
            internal loop + coverage, a full sweep is normally a single call.
        overwrite: re-fetch family_id even if already present.

    Returns:
        {success, filled, family_covered, failed, skipped, calls_made,
         next_cursor, exhausted, total_targets, errors[]} — pubno-granular
         outcome. exhausted=true means the whole target set is processed. If a
         cap stopped the run early, exhausted=false — resume at next_cursor
         (rare; only when max_calls/time_budget_sec was set).
    """
    import asyncio
    import re as _re
    import time as _time

    if not epo_client.configured():
        return {"success": False, "error": "EPO_NOT_CONFIGURED",
                "detail": "EPO_CONSUMER_KEY/SECRET not set"}

    def _fam_key(pn: str) -> str:
        """Kind-stripped country+number key for family-coverage matching.

        patentdb.canonical_pubno does NOT reliably strip kind codes with a
        digit suffix (US9993166B1 -> ...B1, US9993166A -> ...), so members
        returned by epo_family (which carry kind) would silently miss against
        patentdb keys. This helper strips a trailing kind code (letter +
        optional digits) after the numeric body so US9993166B1, US9993166A2
        and US9993166 all collapse to the same key.
        """
        s = _re.sub(r"[\s/\-,\.]+", "", (pn or "")).upper()
        m = _re.match(r"^([A-Z]{2})?(.+?)([A-Z]\d*)?$", s)
        if not m:
            return s
        cc = m.group(1) or ""
        body = m.group(2) or ""
        return f"{cc}{body}"

    # ── build the target list ──────────────────────────────────────
    if from_pool_missing:
        conn = _pdb._connect()
        try:
            if overwrite:
                rows = conn.execute(
                    "SELECT pubno FROM patents ORDER BY pubno"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT pubno FROM patents "
                    "WHERE family_id IS NULL OR TRIM(family_id)='' ORDER BY pubno"
                ).fetchall()
            targets = [r["pubno"] for r in rows]
        finally:
            conn.close()
    else:
        targets = [p.strip() for p in (pubnos or []) if p and p.strip()]

    if not targets:
        return {"success": True, "done": 0, "filled": 0, "failed": 0,
                "skipped": 0, "calls_made": 0, "next_cursor": cursor,
                "exhausted": True, "errors": [],
                "note": "no targets (empty list or all backfilled)"}

    total = len(targets)
    start = max(0, cursor)
    filled = failed = skipped = calls_made = family_covered = 0
    errors: List[Dict[str, Any]] = []
    _t0 = _time.monotonic()
    _budget = time_budget_sec if time_budget_sec and time_budget_sec > 0 else None
    _cap = max_calls if (max_calls is not None and max_calls > 0) else None

    def _stop() -> Optional[str]:
        # returns a reason string if the run should halt early, else None
        if _cap is not None and calls_made >= _cap:
            return "max_calls"
        if _budget is not None and (_time.monotonic() - _t0) >= _budget:
            return "time_budget"
        return None

    # ── family-coverage cache ──────────────────────────────────────
    # epo_family is single-number but ONE call returns the WHOLE INPADOC
    # family (e.g. US9993166B1 → 151 members). So we query one member, then
    # stamp the same family_id onto EVERY in-pool member in one shot — the
    # API-call count collapses from |targets| to (#distinct families).
    # `covered`: normalized-pubno → family_id already stamped this run.
    # Keyed by canonical_pubno (country+number, kind-stripped) because
    # family() returns members WITH kind codes (US9993166B1) while patentdb
    # pubno keys are kind-stripped — a raw string compare would silently miss.
    covered: Dict[str, str] = {}
    target_keys = {_fam_key(p): p for p in targets}
    i = start
    stop_reason: Optional[str] = None

    while i < total:
        # cap check BEFORE spending an API call (coverage/skip steps are free
        # and continue regardless — they cost no EPO call)
        pub = targets[i]
        pub_key = _fam_key(pub)

        # already stamped by an earlier family in this run — zero API cost
        if pub_key in covered:
            family_covered += 1
            i += 1
            continue

        # skip already-filled when not overwriting (explicit pubnos path)
        if not overwrite and not from_pool_missing:
            existing = _pdb.query(publication_number=pub)
            if existing.get("found"):
                fid = (existing.get("patent") or {}).get("family_id")
                if fid and str(fid).strip():
                    skipped += 1
                    i += 1
                    continue

        # this row needs a real EPO call — honor the cap HERE (before spending)
        stop_reason = _stop()
        if stop_reason:
            break

        try:
            res = await epo_client.family(pub)
            calls_made += 1
            fid = res.get("family_id")
            if res.get("success") and fid:
                fid_s = str(fid)
                # ── family coverage: stamp EVERY in-pool member at once ──
                members = res.get("members") or [pub]
                stamped_this_family = 0
                for m in members:
                    m_key = _fam_key(m)
                    if m_key in covered:
                        continue
                    # only stamp members that are actually in our target set,
                    # OR the queried pub itself (always stamp the seed)
                    orig = target_keys.get(m_key)
                    if orig is None and m_key != pub_key:
                        continue
                    write_pub = orig if orig is not None else m
                    _pdb.put(write_pub, fields={"family_id": fid_s},
                             overwrite=overwrite)
                    covered[m_key] = fid_s
                    stamped_this_family += 1
                # the seed counts as a real fill; extra members are coverage
                filled += 1
                if stamped_this_family > 1:
                    family_covered += stamped_this_family - 1
            else:
                failed += 1
                errors.append({"pubno": pub,
                               "error": res.get("error") or "no_family_id"})
        except Exception as e:  # noqa: BLE001
            calls_made += 1
            failed += 1
            errors.append({"pubno": pub, "error": str(e)})

        i += 1
        # throttle: EPO OPS 15/min → ~4s/call, only when another real call may
        # follow. Skip the sleep if the next stop check would halt us anyway.
        if i < total and _stop() is None:
            await asyncio.sleep(4.2)

    exhausted = i >= total
    return {
        "success": True,
        "filled": filled,
        "family_covered": family_covered,
        "failed": failed,
        "skipped": skipped,
        "calls_made": calls_made,
        "next_cursor": i,
        "exhausted": exhausted,
        "stopped_early": stop_reason,
        "total_targets": total,
        "errors": errors[:50],
    }


@mcp.tool(annotations=_RO)
async def patent_family_backfill_status(
    pool_file: Optional[str] = "/patentdb/pool_membership.jsonl",
) -> Dict[str, Any]:
    """Progress snapshot of the INPADOC family_id backfill — read-only.

    Counts filled vs missing family_id rows and distinct families in patentdb.
    If pool_file (a pool_membership.jsonl visible inside the container, e.g.
    under /patentdb/) exists, also reports pool-level coverage: how many pool
    pubnos hit the DB and how many of those already carry a family_id.

    Use this to watch a long-running backfill without touching the DB.

    Returns:
        {success, total_rows, family_filled, family_missing, pct,
         distinct_families, pool?: {pool_uniq, hit_db, family_filled}}
    """
    import json as _json
    import os as _os

    conn = _pdb._connect()
    try:
        total = conn.execute("SELECT COUNT(*) FROM patents").fetchone()[0]
        filled = conn.execute(
            "SELECT COUNT(*) FROM patents "
            "WHERE family_id IS NOT NULL AND TRIM(family_id)<>''"
        ).fetchone()[0]
        fams = conn.execute(
            "SELECT COUNT(DISTINCT family_id) FROM patents "
            "WHERE family_id IS NOT NULL AND TRIM(family_id)<>''"
        ).fetchone()[0]
        out: Dict[str, Any] = {
            "success": True,
            "total_rows": total,
            "family_filled": filled,
            "family_missing": total - filled,
            "distinct_families": fams,
            "pct": round(filled * 100.0 / total, 1) if total else 0.0,
        }
        if pool_file and _os.path.exists(pool_file):
            pubs: List[str] = []
            with open(pool_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        pubs.append(_json.loads(line)["pubno"])
                    except Exception:  # noqa: BLE001
                        continue
            uniq = list(dict.fromkeys(pubs))
            hit = pool_filled = 0
            for j in range(0, len(uniq), 500):
                chunk = uniq[j:j + 500]
                q = ",".join("?" * len(chunk))
                r = conn.execute(
                    "SELECT COUNT(*), SUM(CASE WHEN family_id IS NOT NULL "
                    "AND TRIM(family_id)<>'' THEN 1 ELSE 0 END) "
                    f"FROM patents WHERE pubno IN ({q})",
                    chunk,
                ).fetchone()
                hit += r[0] or 0
                pool_filled += r[1] or 0
            out["pool"] = {
                "pool_uniq": len(uniq),
                "hit_db": hit,
                "family_filled": pool_filled,
            }
        return out
    finally:
        conn.close()


@mcp.tool()
async def patent_family_dedup(
    pool_file: str = "/patentdb/pool_membership.jsonl",
    out_file: str = "/patentdb/b_layer_representatives.json",
) -> Dict[str, Any]:
    """Family-level dedup + representative selection over a search pool
    (B-layer core-set selection).

    Joins pool pubnos (from a pool_membership.jsonl) against patentdb, groups
    rows by INPADOC family_id (rows without family_id form singleton groups),
    and picks ONE representative per group by content completeness:

        score = len(claim1)*2 + len(abstract) + len(cpc) + len(ipc)
                + 500 if publication_date else 0
                + 500 if priority_date else 0
        tiebreak: earliest publication_date, then pubno lexicographic.

    Pure read on patentdb; writes the full representative list as JSON to
    out_file (put it under /patentdb/ so the host sees it via the bind mount).
    Idempotent — re-run any time; results improve as family backfill fills in.

    Args:
        pool_file: pool_membership.jsonl path visible inside the container.
        out_file: where to write the full JSON result.

    Returns:
        {success, summary:{pool_uniq_pubno, hit_db, miss_db, total_groups,
         family_groups, single_groups, multi_member_family_groups,
         collapsed_by_family_dedup, b_layer_representatives}, out_file}
    """
    import json as _json
    import os as _os
    from collections import defaultdict as _dd

    if not _os.path.exists(pool_file):
        return {"success": False, "error": "POOL_FILE_NOT_FOUND",
                "detail": pool_file}

    pool: List[str] = []
    with open(pool_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                pool.append(_json.loads(line)["pubno"])
            except Exception:  # noqa: BLE001
                continue
    pool_uniq = list(dict.fromkeys(pool))
    if not pool_uniq:
        return {"success": False, "error": "POOL_EMPTY", "detail": pool_file}

    def _score(r: Any) -> int:
        content = (len(r["claim1"] or "") * 2 + len(r["abstract"] or "")
                   + len(r["cpc_codes"] or "") + len(r["ipc_codes"] or ""))
        biblio = ((500 if r["publication_date"] else 0)
                  + (500 if r["priority_date"] else 0))
        return content + biblio

    conn = _pdb._connect()
    try:
        rows: List[Any] = []
        for j in range(0, len(pool_uniq), 500):
            chunk = pool_uniq[j:j + 500]
            q = ",".join("?" * len(chunk))
            rows.extend(conn.execute(
                "SELECT pubno, country, kind, family_id, title_orig, "
                "abstract, claim1, cpc_codes, ipc_codes, publication_date, "
                f"priority_date FROM patents WHERE pubno IN ({q})",
                chunk,
            ).fetchall())
    finally:
        conn.close()

    hit = len(rows)
    groups: Dict[str, List[Any]] = _dd(list)
    for r in rows:
        fid = r["family_id"]
        key = (f"FAM:{fid}" if fid and str(fid).strip()
               else f"SINGLE:{r['pubno']}")
        groups[key].append(r)

    reps: List[Dict[str, Any]] = []
    multi = 0
    for key, members in groups.items():
        members_sorted = sorted(members, key=lambda r: (
            -_score(r),
            r["publication_date"] or "99999999",
            r["pubno"],
        ))
        rep = members_sorted[0]
        if key.startswith("FAM:") and len(members) > 1:
            multi += 1
        reps.append({
            "rep_pubno": rep["pubno"],
            "family_id": (str(rep["family_id"]).strip()
                          if rep["family_id"] else None),
            "group_key": key,
            "group_size": len(members),
            "country": rep["country"],
            "rep_score": _score(rep),
            "member_pubnos": [m["pubno"] for m in members_sorted],
            "collapsed": len(members) - 1,
        })
    reps.sort(key=lambda x: (-x["group_size"], x["group_key"]))

    summary = {
        "pool_uniq_pubno": len(pool_uniq),
        "hit_db": hit,
        "miss_db": len(pool_uniq) - hit,
        "total_groups": len(groups),
        "family_groups": sum(1 for k in groups if k.startswith("FAM:")),
        "single_groups": sum(1 for k in groups if k.startswith("SINGLE:")),
        "multi_member_family_groups": multi,
        "collapsed_by_family_dedup": sum(r["collapsed"] for r in reps),
        "b_layer_representatives": len(reps),
    }
    with open(out_file, "w", encoding="utf-8") as f:
        _json.dump({"summary": summary, "representatives": reps}, f,
                   ensure_ascii=False, indent=2)
    return {"success": True, "summary": summary, "out_file": out_file}


@mcp.tool(annotations=_RO)
async def epo_biblio(publication_number: str) -> Dict[str, Any]:
    """Get official bibliographic data + abstract for a publication via EPO OPS.

    Fills the abstract/title/applicant/IPC for patents that Google/BigQuery
    couldn't supply in-band. Returns {title, abstract, applicants, ipc}.
    """
    return await epo_client.biblio(publication_number)


async def _epo_search_impl(cql: str, range: str = "1-25") -> Dict[str, Any]:
    """Search EPO OPS published data with a CQL query (official, global).

    CQL examples: 'pa=faceheart' (applicant), 'in=poh' (inventor),
    'txt=photoplethysmography and ic=A61B5/024' (text + IPC), 'pn=US11213256'.
    `range` paginates (e.g. "1-25", "26-50"; max 100/page, 2000 total).
    Returns {total, count, results:[publication numbers]}.
    """
    return await epo_client.search(cql, range_=range)


# =====================================================================
# Unified search dispatcher — the ONLY search-class MCP tool
# =====================================================================

@mcp.tool(annotations=_RO)
async def patent_search(
    cpc: Optional[str] = None,
    ipc: Optional[str] = None,
    uspc: Optional[str] = None,
    keyword: Optional[str] = None,
    keyword_field: str = "TI/AB",
    applicant: Optional[str] = None,
    inventor_country: Optional[str] = None,
    pub_number: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    databases: Optional[List[str]] = None,
    num: int = 30,
    skip: int = 0,
    allow_scraping: bool = False,
) -> Dict[str, Any]:
    """Unified patent SEARCH — the single search entry point. The source ladder
    is BUILT IN: TIPO GPSS (official, primary) → EPO OPS → USPTO PPUBS →
    (gated) Google Patents. You do NOT pick a source; the server routes by
    credential availability and query-axis capability, and records every
    level's attempt in `provenance` for audit.

    Scraping gate: the Google Patents tail is a scraper and only runs with
    allow_scraping=True (requires explicit user authorization). When all
    official sources miss and scraping is not authorized, the call fails fast
    with error_code=SCRAPING_REQUIRED — never a silent fallback.

    Args:
        cpc: CPC classification (e.g. "G06Q50/18"; " AND "/" OR " combinable).
        ipc: IPC classification.
        uspc: USPC class/subclass (e.g. "705/300") — routes directly to PPUBS
            (US-only axis; other sources don't support USPC).
        keyword: free-text keyword; `keyword_field` picks the GPSS field
            (TI, AB, CL, "TI/AB", "TI/AB/CL").
        applicant: applicant/assignee name.
        inventor_country: inventor country code (GPSS only).
        pub_number: publication number for a direct lookup (works across
            jurisdictions via GPSS PN).
        date_from/date_to: publication date bounds, YYYYMMDD.
        databases: GPSS patDB list (USA,USB,CNA,CNB,TWA,TWB…); maps to
            country filters on other sources.
        num/skip: pagination. Note: the EPO level fetches bibliographic data
            per hit under a 15/min throttle — large num gets truncated there
            (provenance notes `biblio_truncated`).
        allow_scraping: explicit authorization for the Google Patents tail
            (default False).

    Returns {success, records[], source, provenance[], gaps[], total} —
    records use the unified screening record schema (missing fields are
    honestly blank and listed in `gaps`); on failure `error_code` is one of
    INVALID_PARAMS / SCRAPING_REQUIRED / ALL_SOURCES_MISS.

    consider: patentmcp_kb_query — recall distilled search methodology,
    source-API specs and known failure modes before designing the query.
    """
    spec = _sd.normalize_query(
        cpc=cpc, ipc=ipc, uspc=uspc, keyword=keyword,
        keyword_field=keyword_field, applicant=applicant,
        inventor_country=inventor_country, pub_number=pub_number,
        date_from=date_from, date_to=date_to, databases=databases,
        num=num, skip=skip, allow_scraping=allow_scraping,
    )
    envelope = await _sd.dispatch_search(
        spec,
        gpss_client=gpss_client,
        epo_client=epo_client,
        ppubs_client=ppubs_client,
        gpatents_client=gpatents_client,
    )
    # patentdb inline-absorb side-effect (DD-11 延伸：每次檢索命中即吸收書目，
    # 零額外 toolcall、零網路）。永不阻斷檢索回傳；吸收結果記入 envelope 供稽核。
    if envelope.get("success") and envelope.get("records"):
        try:
            cost = "high" if envelope.get("source") == "gpatents" else "low"
            absorb = _pdb.import_records(envelope["records"], acquisition_cost=cost)
            envelope["patentdb_absorb"] = absorb
        except Exception as e:  # noqa: BLE001 — absorb must never break search
            logger.warning(f"patentdb absorb failed for patent_search: {e}")
            envelope["patentdb_absorb"] = {"error": "absorb_failed", "detail": str(e)}
    return envelope


@mcp.tool()
async def patent_bulk(
    source: Optional[str] = None,
    ipc: Optional[str] = None,
    cpc: Optional[str] = None,
    uspc: Optional[str] = None,
    keyword: Optional[str] = None,
    keyword_field: str = "TI/AB",
    applicant: Optional[str] = None,
    inventor_country: Optional[str] = None,
    databases: Optional[List[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    num: int = 100,
    skip: int = 0,
    slice_plan: bool = False,
) -> Dict[str, Any]:
    """Unified BULK harvest — exhaustively pull a result set from ONE explicitly
    chosen source in a single call, with server-side auto-pagination (and, for
    EPO, biblio fan-out). The single bulk entry point (patent_bulk_export /
    patent_bulk_harvest / epo_bulk_harvest were folded into this).

    `source` is REQUIRED and has NO default — you must commit to "gpss" or "epo".
    A missing/other source returns INVALID_PARAMS and touches NO backend. There
    is deliberately no auto-route and no cross-source fallback: the two backends
    differ sharply in quota / throttle / coverage, so an implicit default would
    silently blow the wrong quota. Choosing the source = committing to its cost.

    source="gpss" (TIPO GPSS):
      • no keyword → classification-axis EXPORT (pure ipc/cpc/uspc, full expFld
        forced). *** To pull a WHOLE axis, DO NOT pass keyword *** — a keyword
        AND-narrows the axis and can produce false zero-hits.
      • keyword given → keyword HARVEST (keyword + optional classification, GPSS
        field-internal and/or/not honored via keyword_field).
      • Quota model: TIPO time-window quota; num can be raised large (suggest
        ~2000) to land a multi-thousand-row slice in one call — GPSS books biblio
        inline per page so there is no fan-out timeout risk. Hard-capped at 5000.
      • One collect-then-absorb at the end (no fan-out timeout window).

    source="epo" (EPO OPS):
      • keyword boolean (AND/OR/NOT + "quoted phrases" + parens) is translated to
        CQL; classification via ipc/cpc, applicant via pa=.
      • Throttle model: OPS ~15/min + a deep-paging skip wall (~2000); every ref
        needs a second-stage biblio fetch. Keep num MODEST (default 100 = one OPS
        page) so a single call stays under the client timeout; raise to 300-500
        only on a fast link. Each page is absorbed the moment its biblio fan-out
        finishes (per-page absorb) so a timeout never discards landed pages.
      • EPO IGNORES `keyword_field` (always searches txt=), and `uspc`,
        `databases`, `inventor_country` (no EPO equivalent) — passing them has
        no effect on the EPO branch.

    Continuation (both sources): the envelope carries `next_skip` and `exhausted`.
    To resume a partial pull, re-call with skip=<returned next_skip>; the patentdb
    COALESCE upsert makes resume idempotent (re-running never clobbers non-empty
    rows). `exhausted=True` means total (or the EPO skip wall) was reached.

    EPO large-population workflow (slice_plan=True, source MUST be "epo"):
    OPS caps deep paging at skip=2000, so a query whose total exceeds ~2000
    cannot be pulled in one continuation chain. When total > 2000:
      1. Call patent_bulk(source="epo", keyword=.., date_from=.., date_to=..,
         slice_plan=True) — this count-probes only (ZERO records, ZERO absorb)
         and returns a slice plan: {slices:[{date_from,date_to,total}...],
         sum_check, probe_calls}. Each slice's total < 2000.
      2. For each slice, harvest normally: patent_bulk(source="epo",
         date_from=slice.date_from, date_to=slice.date_to, keyword=..) and
         resume in-slice via the returned next_skip until exhausted.
    slice_plan is EPO-only: gpss+slice_plan → INVALID_PARAMS (GPSS expSkip has no
    skip wall, so no slicing is needed). No date range + total>2000 →
    DATE_RANGE_REQUIRED; slice leaf-sum drift >5% → SLICE_INEFFECTIVE.
    For non-slice_plan EPO calls whose total exceeds 2000 and is not yet
    exhausted, the envelope carries a `slice_hint` (advisory, non-blocking).

    consider: patentmcp_kb_query — recall source quota models, slicing
    strategies and harvest failure modes before committing to a bulk pull.

    Args:
        source: REQUIRED — "gpss" or "epo". No default; anything else →
            INVALID_PARAMS, zero backend calls.
        ipc/cpc/uspc: classification axes (uspc gpss-only; EPO ignores uspc).
        keyword: free-text boolean; gpss+keyword → harvest, gpss+no-keyword →
            axis export, epo → CQL. To pull a whole gpss axis, leave keyword empty.
        keyword_field: GPSS field (TI/AB/CL...); EPO ignores it.
        applicant/inventor_country: AX / IY (inventor_country gpss-only).
        databases: GPSS patDB list (gpss-only; EPO ignores it).
        date_from/date_to: publication-date bounds (ISO or YYYYMMDD).
        num: target rows (auto-paginated). Default 100 (safe for EPO's one-page /
            timeout budget); for gpss you can raise it (~2000) to land a big slice.
        skip: starting offset; pass the returned `next_skip` to continue.
        slice_plan: EPO-only planning mode. True → count-probe the population and
            return a date-slice plan (zero records / zero absorb) so a >2000
            query can be harvested slice-by-slice. gpss+slice_plan →
            INVALID_PARAMS.

    Returns {success, records[], source, provenance[], gaps[], total, next_skip,
    exhausted, patentdb_absorb, error_code?}. error_code is INVALID_PARAMS
    (bad/missing source or axis) / GPSS_NOT_CONFIGURED / GPSS_ERROR /
    EPO_NOT_CONFIGURED / EPO_ERROR.
    """
    spec = _sd.normalize_query(
        ipc=ipc, cpc=cpc, uspc=uspc, keyword=keyword, keyword_field=keyword_field,
        applicant=applicant, inventor_country=inventor_country,
        databases=databases, date_from=date_from, date_to=date_to,
        num=num, skip=skip,
    )
    if slice_plan:
        # Planning-only: EPO-only, count-probe + slice plan, ZERO records/absorb.
        if source != "epo":
            return {
                "success": False, "error_code": "INVALID_PARAMS",
                "message": ("slice_plan 僅適用 source='epo';GPSS expSkip 自動分頁"
                            "無 skip wall,不需切片"),
            }
        return await _sd.epo_slice_plan(spec, epo_client=epo_client)
    if source == "epo":
        # EPO per-page absorb: land each page NOW so a client-side timeout on the
        # biblio fan-out keeps whatever already landed (COALESCE upsert is
        # resume-safe). Mirrors the retired epo_bulk_harvest wrapper.
        absorbed = {"imported": 0, "updated": 0, "skipped": 0}

        def _absorb_page(page_records: List[Dict[str, Any]]) -> None:
            res = _pdb.import_records(page_records, acquisition_cost="low")
            for k in absorbed:
                absorbed[k] += int(res.get(k, 0) or 0)

        envelope = await _sd.bulk(
            spec, source, gpss_client=gpss_client, epo_client=epo_client,
            absorb_cb=_absorb_page)
        if envelope.get("source") == "epo":
            envelope["patentdb_absorb"] = absorbed
        # Advisory (non-blocking): a >wall population can't be fully pulled in one
        # continuation chain (OPS skip wall); hint the slice_plan workflow.
        _total = envelope.get("total")
        if (envelope.get("success") and isinstance(_total, int)
                and _total > _sd._EPO_SKIP_WALL and not envelope.get("exhausted")):
            envelope["slice_hint"] = (
                "total exceeds OPS skip wall; use slice_plan=true")
        return envelope

    # gpss (or invalid source → INVALID_PARAMS from _sd.bulk, zero backend calls).
    envelope = await _sd.bulk(
        spec, source, gpss_client=gpss_client, epo_client=epo_client)
    # GPSS collect-then-absorb at the end (mirrors the retired gpss wrappers).
    if envelope.get("success") and envelope.get("records"):
        try:
            absorb = _pdb.import_records(envelope["records"], acquisition_cost="low")
            envelope["patentdb_absorb"] = absorb
        except Exception as e:  # noqa: BLE001 — absorb must never break harvest
            logger.warning(f"patentdb absorb failed for patent_bulk: {e}")
            envelope["patentdb_absorb"] = {"error": "absorb_failed", "detail": str(e)}
    return envelope


# ── retired bulk tools → TOOL_RENAMED redirect (plans/patentmcp_bulk-entry-
# unification DD-5). One release cycle of typed redirects so stale skill
# projections / playbooks get a correction pointing at patent_bulk. Zero
# backend calls; signatures preserved so old callers still bind.

def _bulk_renamed(source: str, note_extra: str = "") -> Dict[str, Any]:
    return {
        "success": False,
        "error_code": "TOOL_RENAMED",
        "use": "patent_bulk",
        "note": (
            "This bulk tool was unified into patent_bulk. Re-issue via "
            f"patent_bulk with source='{source}': carry every original argument "
            "over unchanged (ipc/cpc/uspc/keyword/keyword_field/applicant/"
            "inventor_country/databases/date_from/date_to/num/skip) and add "
            f"source='{source}'." + (f" {note_extra}" if note_extra else "")
        ),
    }


@mcp.tool()
async def patent_bulk_export(
    ipc: Optional[str] = None,
    cpc: Optional[str] = None,
    uspc: Optional[str] = None,
    databases: Optional[List[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    num: int = 2000,
    skip: int = 0,
) -> Dict[str, Any]:
    """[RENAMED -> patent_bulk] Returns a TOOL_RENAMED redirect envelope; does
    NOT run a search. Call patent_bulk(source='gpss', ...) with no keyword for a
    classification-axis export."""
    return _bulk_renamed("gpss")


@mcp.tool()
async def patent_bulk_harvest(
    ipc: Optional[str] = None,
    cpc: Optional[str] = None,
    uspc: Optional[str] = None,
    keyword: Optional[str] = None,
    keyword_field: str = "TI/AB",
    inventor_country: Optional[str] = None,
    applicant: Optional[str] = None,
    databases: Optional[List[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    num: int = 2000,
    skip: int = 0,
) -> Dict[str, Any]:
    """[RENAMED -> patent_bulk] Returns a TOOL_RENAMED redirect envelope; does
    NOT run a search. Call patent_bulk(source='gpss', keyword=...) for a
    keyword harvest."""
    return _bulk_renamed("gpss")


@mcp.tool()
async def epo_bulk_harvest(
    ipc: Optional[str] = None,
    cpc: Optional[str] = None,
    keyword: Optional[str] = None,
    keyword_field: str = "TI/AB",
    applicant: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    num: int = 100,
    skip: int = 0,
) -> Dict[str, Any]:
    """[RENAMED -> patent_bulk] Returns a TOOL_RENAMED redirect envelope; does
    NOT run a search. Call patent_bulk(source='epo', ...) for the EPO harvest
    (keyword_field/uspc/databases/inventor_country are ignored by EPO)."""
    return _bulk_renamed("epo")


# =====================================================================
# Deprecation stubs — retired search tools (BR_20260706)
# One release-cycle TOOL_RENAMED redirects so stale skill projections /
# old playbooks get a typed correction instead of an unknown-tool loop.
# =====================================================================

_TOOL_RENAMED_ENVELOPE = {
    "success": False,
    "error_code": "TOOL_RENAMED",
    "use": "patent_search",
    "note": (
        "This search tool was retired in 0.3.0 (commit 7c4330d): all search "
        "entry points were unified into patent_search, whose source ladder "
        "(TIPO GPSS -> EPO OPS -> USPTO PPUBS -> gated Google Patents) is "
        "built in. Re-issue the query via patent_search; axes cpc/ipc/keyword/"
        "applicant/pub_number/date_from/date_to/databases/num/skip carry over "
        "unchanged. The scraper tail needs allow_scraping=True."
    ),
}


@mcp.tool()
async def gpss_search(
    cpc: Optional[str] = None,
    ipc: Optional[str] = None,
    keyword: Optional[str] = None,
    keyword_field: Optional[str] = "TI/AB",
    inventor_country: Optional[str] = None,
    applicant: Optional[str] = None,
    pub_number: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    databases: Optional[List[str]] = None,
    patent_type: Optional[str] = None,
    case_type: Optional[str] = None,
    fields: Optional[str] = None,
    num: Optional[int] = 30,
    skip: Optional[int] = 0,
) -> Dict[str, Any]:
    """[RENAMED -> patent_search] Retired 0.3.0. Returns a TOOL_RENAMED
    redirect envelope; does NOT run a search. Call patent_search instead —
    same cpc/ipc/keyword/databases axes, source ladder built in."""
    return dict(_TOOL_RENAMED_ENVELOPE)


@mcp.tool()
async def epo_search(cql: Optional[str] = None, range: str = "1-25") -> Dict[str, Any]:
    """[RENAMED -> patent_search] Retired 0.3.0. Returns a TOOL_RENAMED
    redirect envelope; does NOT run a search. The EPO level is built into
    patent_search's source ladder (single-number tools epo_family /
    epo_biblio remain available)."""
    return dict(_TOOL_RENAMED_ENVELOPE)


@mcp.tool()
async def gpatents_search(
    query: Optional[str] = None,
    countries: Optional[List[str]] = None,
    num: Optional[int] = 10,
    page: Optional[int] = 0,
    before: Optional[str] = None,
    after: Optional[str] = None,
    status: Optional[str] = None,
    type: Optional[str] = None,
) -> Dict[str, Any]:
    """[RENAMED -> patent_search] Retired 0.3.0. Returns a TOOL_RENAMED
    redirect envelope; does NOT run a search. The Google Patents tail is the
    gated last level of patent_search (allow_scraping=True required);
    single-number tools gpatents_get / gpatents_download_* remain."""
    return dict(_TOOL_RENAMED_ENVELOPE)


# =====================================================================
# R15 self-describing guide surface
# /plans/mcp_r15-self-describing-guide DD-1/DD-5/DD-6
# =====================================================================

_GUIDE_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


@mcp.tool(annotations=_GUIDE_ANNOTATIONS)
async def patentmcp_init() -> str:
    """Read-only: returns patentmcp's usage doctrine, no side effects (R15 self-describing organism).

    Despite the `init` name this makes NO state changes — call it ONCE before
    first use to receive, in-band, the complete patentworks usage doctrine in one
    call: cross-tool
    tradeoffs (multi-source search flow selection + the GPSS>EPO>PPUBS>gated
    Google Patents source ladder), pre-call disciplines (patent work-pool data
    tree spec, scratch->/tmp, scraping authorization), organ coordination
    (container + UDS transport + patentworks skill + host-local scripts +
    WebDAV working cache), and counter-intuitive gotchas. This is delivered
    context (arrives in-band at the action boundary) rather than doctrine you
    must remember to load. Same content as `prompts/get patentmcp_init`
    (byte-identical, single source). No arguments."""
    return _guide_doctrine()


@mcp.prompt(
    name="patentmcp_init",
    description=(
        "Read-only: patentmcp's usage doctrine, no side effects (R15 self-describing organism): "
        "cross-tool tradeoffs, pre-call disciplines, organ coordination, and "
        "gotchas. Same content as the patentmcp_init tool; this prompts/get "
        "face is reachable by bare MCP clients. No arguments."
    ),
)
def patentmcp_init_prompt() -> str:
    """prompts/get face of the R15 guide. Byte-identical to the
    patentmcp_init TOOL — both project _guide_doctrine() (the patentworks
    SKILL.md single source), so the doctrine lives in exactly one place
    (R15.5 no-drift)."""
    return _guide_doctrine()


# =====================================================================
# R16 domain-KB serving (plan mcp_r16-domain-kb)
# Read-only in-band serving of the repo ragbase KB (.specbase/
# ragbase.sqlite; host-side producer: specbase producer.ts
# ragbase_distill). DD-3: the mount is rw (WAL side files need a writable
# dir) but read-only is enforced at the CONNECTION layer — URI mode=ro +
# PRAGMA query_only=ON, per-request, zero KB-write tools on the MCP
# surface. DD-1/DD-4: errors follow patentmcp's dict-envelope convention
# ({success:false, error_code, ...}) — fail-fast, no path guessing, no
# empty-hits masquerade. Query semantics mirror specbase gate.ts /
# bodesign reference impl (DD-2).
# =====================================================================

_KB_REMEDY = ("KB lives host-side at <repo>/.specbase/ragbase.sqlite; "
              "distill via specbase producer.ts (ragbase_distill); mount is "
              "live, no restart needed.")
# ragbase FTS5 uses the trigram tokenizer (specbase ragbase-schema): only
# runs of >=3 codepoints are indexed, so a shorter token can NEVER match
# via FTS (R16.6 — degradation must be self-described, see _kb_match_plan).
_KB_MIN_TRIGRAM = 3


class _KbError(Exception):
    """Typed KB serving error. `code` is the machine error_code
    (KB_UNAVAILABLE / KB_BAD_QUERY / KB_OBJECT_NOT_FOUND per
    plans/mcp_r16-domain-kb/errors.md); str() is the human message."""

    def __init__(self, code: str, message: str, remedy: Optional[str] = None):
        super().__init__(message)
        self.code = code
        self.remedy = remedy

    def envelope(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"success": False, "error_code": self.code,
                               "message": str(self)}
        if self.remedy:
            out["remedy"] = self.remedy
        return out


def _kb_connect():
    """Per-request read-only sqlite connection (DD-3/DD-6). Env-located; any
    unavailability raises KB_UNAVAILABLE with the remedy — never a guessed
    path, never a silent empty store."""
    import sqlite3
    from pathlib import Path
    db_path = (os.environ.get("PATENTS_KB_DB") or "").strip()
    if not db_path:
        raise _KbError("KB_UNAVAILABLE", "PATENTS_KB_DB env is not set", _KB_REMEDY)
    if not Path(db_path).is_file():
        raise _KbError("KB_UNAVAILABLE", f"KB sqlite not found at {db_path}", _KB_REMEDY)
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise _KbError("KB_UNAVAILABLE", f"cannot open KB at {db_path}: {exc}", _KB_REMEDY) from exc
    try:
        conn.execute("PRAGMA query_only=ON")
    except sqlite3.Error as exc:
        conn.close()
        raise _KbError("KB_UNAVAILABLE", f"cannot open KB at {db_path}: {exc}", _KB_REMEDY) from exc
    conn.row_factory = sqlite3.Row
    return conn


def _kb_match_plan(q: str) -> Dict[str, Any]:
    """DD-2: specbase gate.ts query-planning semantics, not reinvented.
    All tokens >=3 codepoints -> FTS AND ('fts'); all <3 -> LIKE scan
    ('like-scan', score=0, recency order); mixed -> 'hybrid'."""
    tokens = [t for t in q.split() if t]
    fts_tokens = [t for t in tokens if len(t) >= _KB_MIN_TRIGRAM]
    like_tokens = [t for t in tokens if len(t) < _KB_MIN_TRIGRAM]
    # per-token quoted phrases: FTS operator-injection guard (a:b stays literal)
    fts_expr = " AND ".join('"' + t.replace('"', '""') + '"' for t in fts_tokens) or None
    if not like_tokens:
        mode = "fts"
    elif fts_expr is None:
        mode = "like-scan"
    else:
        mode = "hybrid"
    return {"fts_expr": fts_expr, "like_tokens": like_tokens, "mode": mode}


def _kb_like_pattern(token: str) -> str:
    escaped = "".join("\\" + c if c in ("\\", "%", "_") else c for c in token)
    return f"%{escaped}%"


def _kb_source_weight(conn, obj_id: str):
    """Max source_weight (1-7) over the object's distilled_from/extracted_from
    lineage edges (specbase metadata); None when ungraded — never fabricated."""
    weights = []
    for r in conn.execute(
            "SELECT metadata_json FROM ragbase_lineage WHERE source_id = ? "
            "AND edge_type IN ('distilled_from','extracted_from') "
            "AND metadata_json != ''", (obj_id,)).fetchall():
        try:
            w = json.loads(r["metadata_json"]).get("source_weight")
        except (ValueError, AttributeError):
            continue
        if isinstance(w, (int, float)):
            weights.append(w)
    return max(weights) if weights else None


_KB_LIKE_COND = "(o.title LIKE ? ESCAPE '\\' OR o.body_md LIKE ? ESCAPE '\\')"


@mcp.tool(annotations=_GUIDE_ANNOTATIONS)
async def patentmcp_kb_query(q: str, type: Optional[str] = None,
                             limit: int = 10) -> Dict[str, Any]:
    """READ-ONLY, no side effects: query patentmcp's self-shipped patent-practice
    domain KB (the repo ragbase store — distilled, evidence-graded knowledge:
    GPSS/EPO API specs, prior-art search methodology, figure-exhaustion ladder,
    known failure modes, patent-analysis frameworks). Call BEFORE judgment-heavy
    steps (search-query design, source-ladder interpretation, screening
    calibration) to recall what is already known — recall-first (R16.5).

    Query semantics (specbase-identical): whitespace tokens >=3 codepoints ->
    FTS AND (matchMode 'fts'); all <3 (short CJK) -> LIKE scan over title/body,
    score=0, recency-ordered ('like-scan'); mixed -> 'hybrid'. Payload always
    carries matchMode so a degraded 0-hit is distinguishable from true
    no-knowledge. Fail-fast: missing/unmounted KB -> error_code KB_UNAVAILABLE
    + remedy, never empty hits masquerading as no knowledge.

    Args:
        q: query text (required, non-empty).
        type: optional object-type filter (concept|workflow|failure-mode|
            source|asset|extract).
        limit: max hits (default 10, cap 50).

    Returns {success, hits:[{id,type,title,score,confidence,source_weight}],
    matchMode, total}. patentmcp_kb_get(id) returns a hit's full body.
    """
    try:
        q = (q or "").strip()
        if not q:
            raise _KbError("KB_BAD_QUERY", "empty query")
        type_filter = (type or "").strip() or None
        try:
            limit_n = int(limit)
        except (TypeError, ValueError):
            limit_n = 10
        limit_n = min(max(limit_n, 1), 50)
        plan = _kb_match_plan(q)
        conn = _kb_connect()
    except _KbError as exc:
        return exc.envelope()
    try:
        where: List[str] = []
        params: List[Any] = []
        if plan["mode"] == "like-scan":
            base_from = "FROM ragbase_objects o"
            select_score = "0 AS score"
            order = "o.updated_at DESC"
        else:
            base_from = ("FROM ragbase_fts JOIN ragbase_objects o "
                         "ON o.rowid = ragbase_fts.rowid")
            select_score = "bm25(ragbase_fts) AS score"
            order = "bm25(ragbase_fts)"
            where.append("ragbase_fts MATCH ?")
            params.append(plan["fts_expr"])
        for t in plan["like_tokens"]:
            where.append(_KB_LIKE_COND)
            p = _kb_like_pattern(t)
            params.extend([p, p])
        if type_filter:
            where.append("o.type = ?")
            params.append(type_filter)
        where_sql = " AND ".join(where) or "1=1"
        total = conn.execute(
            f"SELECT count(*) {base_from} WHERE {where_sql}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT o.id, o.type, o.title, o.confidence, {select_score} "
            f"{base_from} WHERE {where_sql} ORDER BY {order} LIMIT ?",
            [*params, limit_n]).fetchall()
        hits = [{"id": r["id"], "type": r["type"], "title": r["title"],
                 "score": r["score"], "confidence": r["confidence"],
                 "source_weight": _kb_source_weight(conn, r["id"])} for r in rows]
        return {"success": True, "query": q, "matchMode": plan["mode"],
                "hits": hits, "total": total, "limit": limit_n}
    finally:
        conn.close()


@mcp.tool(annotations=_GUIDE_ANNOTATIONS)
async def patentmcp_kb_get(id: str) -> Dict[str, Any]:
    """READ-ONLY, no side effects: fetch ONE domain-KB object's full distilled
    body (body_md) plus evidence grading (confidence, source_weight) and
    provenance (its distilled_from/extracted_from lineage edges with per-edge
    source_weight). Unknown id -> error_code KB_OBJECT_NOT_FOUND (consider:
    patentmcp_kb_query to find the right id)."""
    try:
        obj_id = (id or "").strip()
        if not obj_id:
            raise _KbError("KB_BAD_QUERY", "id is required")
        conn = _kb_connect()
    except _KbError as exc:
        return exc.envelope()
    try:
        row = conn.execute(
            "SELECT id, type, title, batch_id, locator, confidence, "
            "extraction_status, body_md, metadata_json, captured_at, "
            "updated_at, scope FROM ragbase_objects WHERE id = ?",
            (obj_id,)).fetchone()
        if row is None:
            return _KbError(
                "KB_OBJECT_NOT_FOUND",
                f"{obj_id} not found. consider: patentmcp_kb_query").envelope()
        provenance = []
        for r in conn.execute(
                "SELECT target_id, edge_type, metadata_json FROM ragbase_lineage "
                "WHERE source_id = ? AND edge_type IN "
                "('distilled_from','extracted_from')", (obj_id,)).fetchall():
            weight = None
            if r["metadata_json"]:
                try:
                    w = json.loads(r["metadata_json"]).get("source_weight")
                    if isinstance(w, (int, float)):
                        weight = w
                except (ValueError, AttributeError):
                    pass
            provenance.append({"edge_type": r["edge_type"],
                               "derived_from": r["target_id"],
                               "source_weight": weight})
        out: Dict[str, Any] = {k: row[k] for k in row.keys()}
        out["success"] = True
        out["source_weight"] = _kb_source_weight(conn, obj_id)
        out["provenance"] = provenance
        return out
    finally:
        conn.close()


# =====================================================================
# Cleanup Handler
# =====================================================================

async def cleanup():
    """Clean up resources on shutdown."""
    logger.info("Shutting down USPTO Patent MCP server, cleaning up resources...")
    try:
        await ppubs_client.close()
        await api_client.close()
        await google_bq_client.close()
        await gpatents_client.close()
        await gpss_client.close()
        await epo_client.close()
        logger.info("Cleanup completed successfully")
    except Exception as e:
        logger.error(f"Error during cleanup: {str(e)}")
@mcp.tool()
async def patentmcp_batch_download_figures(publication_numbers: List[str]) -> Dict[str, Any]:
    """Batch download representative figures for a list of patent publication numbers.
    
    Implements a local cooldown (skip list) cache for patents encountering HTTP 503
    errors to prevent locking. Returns a mapping of publication numbers to their staged
    image handles or skipped status.
    """
    import json
    import time
    import tempfile
    
    cooldown_file = os.path.join(tempfile.gettempdir(), "patent_cooldown.json")
    cooldown_data = {}
    if os.path.exists(cooldown_file):
        try:
            with open(cooldown_file, "r") as f:
                cooldown_data = json.load(f)
        except Exception:
            pass
            
    now = time.time()
    cooldown_data = {k: v for k, v in cooldown_data.items() if now - v < 600}
    
    downloaded = {}
    skipped = {}

    # ONE shared GPSS scrape session for the whole batch: the cookie jar /
    # cf_clearance accumulates across every TW item instead of being discarded
    # per patent (the deeper RCA of the ReadTimeout — a fresh client per request
    # looks like a brand-new suspicious client to Cloudflare). Non-TW items route
    # through the report-grade PDF pipeline (extract_representative_figure), NOT
    # the 60x80 index thumbnail (BR_20260628 §2 #3 forbids thumbnails in
    # deliverables; get_patent() never returns representative_figure_url anyway —
    # that field only exists on search()._flatten() results — so the old branch
    # failed for EVERY non-TW patent). Items run sequentially: single-thread is
    # preserved because each GPSS burst takes _GPSS_SCRAPE_LOCK per-burst inside
    # the session methods (the loop itself holds no lock, so a non-TW item's
    # extract_representative_figure -> fetch_patent_pdf -> gpss_pdf re-entry
    # cannot deadlock on the non-reentrant lock).
    session = _GpssScrapeSession()
    try:
        for pub in publication_numbers:
            pub = pub.strip()
            if not pub:
                continue

            if pub in cooldown_data:
                skipped[pub] = {
                    "reason": "503_cooldown",
                    "remaining_seconds": int(600 - (now - cooldown_data[pub]))
                }
                continue

            try:
                if pub.upper().startswith("TW"):
                    res = await session.fetch_representative_figure(pub)
                else:
                    # Report-grade: PDF -> FIG.1 page -> high-DPI PNG.
                    res = await extract_representative_figure(pub)

                if res.get("success") or "download_url" in res:
                    downloaded[pub] = res
                else:
                    err_str = str(res.get("error", "")).lower()
                    if "503" in err_str or "quota" in err_str or "unavailable" in err_str or "limit" in err_str:
                        cooldown_data[pub] = now
                        skipped[pub] = {"reason": "503_detected_added_to_cooldown", "error": res.get("error")}
                    else:
                        skipped[pub] = {"reason": "failed", "error": res.get("error")}

            except Exception as e:
                err_str = str(e).lower()
                if "503" in err_str or "unavailable" in err_str:
                    cooldown_data[pub] = now
                    skipped[pub] = {"reason": "503_exception_added_to_cooldown", "error": str(e)}
                else:
                    skipped[pub] = {"reason": "exception", "error": str(e)}
    finally:
        await session.close()

    try:
        with open(cooldown_file, "w") as f:
            json.dump(cooldown_data, f)
    except Exception:
        pass
        
    return {
        "success": True,
        "downloaded": downloaded,
        "skipped": skipped
    }


@mcp.tool()
async def pool_fetch(publication_numbers: List[str]) -> Dict[str, Any]:
    """Fetch per-publication metadata for a patent pool and LAND it as a records
    JSON in the token store (the network/credential half of the old
    patentmcp_analyze_pool). Source ladder per pub: BigQuery → TW GPSS → Google
    Patents scrape → patent_get_claim1. The raw records never flow through the
    model context; the agent then renders charts LOCALLY with
    skills/patentworks/scripts/pool_charts.py over the returned handle.

    Returns {success, handle{token,rel,download_url,...}, count, gaps}. The JSON
    payload is {"records": [...], "gaps": [...]} — records is the same schema the
    old chart pipeline consumed (pub/country/year/assignee/cpc/cpc_group/title/
    abstract/claim1).

    consider: patentmcp_kb_query — recall pool-analysis methodology (TF matrix,
    IPC multilevel, lifecycle S-curve) before shaping the pool.
    """
    import json as _json
    import re

    # 1. Fetch metadata in batch
    records = []
    gaps = []
    
    for pub in publication_numbers:
        pub = pub.strip()
        if not pub:
            continue
            
        rec = {
            "pub": pub,
            "country": pub[:2].upper(),
            "year": "Unknown",
            "assignee": "Unknown",
            "cpc": [],
            "cpc_group": "Unknown",
            "title": "",
            "abstract": "",
            "claim1": ""
        }
        
        # Try BQ
        bq_success = False
        if google_bq_client.client is not None:
            try:
                bq_res = await google_bq_client.get_patent_by_number(pub)
                if bq_res.get("success") and bq_res.get("patent"):
                    pat_data = bq_res["patent"]
                    rec["country"] = pat_data.get("country_code", rec["country"])
                    pdate = pat_data.get("publication_date")
                    if pdate:
                        rec["year"] = str(pdate)[:4]
                    
                    # Extract assignee
                    assignees = pat_data.get("assignee_harmonized", []) or pat_data.get("assignee", [])
                    if assignees and isinstance(assignees, list):
                        rec["assignee"] = assignees[0].get("name", "Unknown") if isinstance(assignees[0], dict) else str(assignees[0])
                        
                    # CPC
                    cpcs = pat_data.get("cpc", [])
                    if cpcs and isinstance(cpcs, list):
                        rec["cpc"] = [c.get("code") for c in cpcs if c.get("code")]
                        if rec["cpc"]:
                            rec["cpc_group"] = rec["cpc"][0][:4]
                            
                    rec["title"] = pat_data.get("title_localized", [{}])[0].get("text", "")
                    rec["abstract"] = pat_data.get("abstract_localized", [{}])[0].get("text", "")
                    bq_success = True
            except BudgetExceededError as e:
                # BQ is a fallback source here; skip (logged) when budget exhausted
                # and let the chain fall through to GPSS.
                logger.warning(f"BQ metadata skipped for {pub} (budget exhausted): {str(e)}")
            except Exception as e:
                logger.warning(f"BQ metadata fetch failed for {pub}: {str(e)}")
                
        # Try TW GPSS Fallback
        if not bq_success and pub.upper().startswith("TW") and gpss_client.configured():
            try:
                db = ["TWA", "TWB"]
                gpss_res = await gpss_client.search(
                    conditions=[GPSSCondition("PN", pub)],
                    databases=db,
                    fields="PN,AD,ID,TI,AB,CL,PA,CS"
                )
                if gpss_res.get("success") and gpss_res.get("data"):
                    api = gpss_res["data"].get("gpss-API", {})
                    patent_content = api.get("patent", {}).get("patentcontent", [])
                    if not isinstance(patent_content, list):
                        patent_content = [patent_content]
                    if patent_content:
                        p_rec = patent_content[0]
                        pdate = p_rec.get("publication-date", {}).get("date", "") or p_rec.get("application-date", {}).get("date", "")
                        if pdate:
                            rec["year"] = str(pdate)[:4]
                        rec["assignee"] = p_rec.get("applicant", {}).get("pa-name", "Unknown") or p_rec.get("assignee", {}).get("pa-name", "Unknown")
                        rec["title"] = p_rec.get("title", {}).get("title-text", "")
                        rec["abstract"] = p_rec.get("abstract", {}).get("abstract-text", "")
                        
                        # CPC / IPC
                        cpc_data = p_rec.get("ipc-info", {}).get("ipc", [])
                        if not isinstance(cpc_data, list):
                            cpc_data = [cpc_data]
                        rec["cpc"] = [c.get("ipc-text", "") for c in cpc_data if c.get("ipc-text")]
                        if rec["cpc"]:
                            rec["cpc_group"] = rec["cpc"][0][:4]
                        bq_success = True
            except Exception as e:
                logger.warning(f"GPSS metadata fetch failed for {pub}: {str(e)}")
                
        # Try Web Scraper Fallback
        if not bq_success:
            try:
                gpat_res = await gpatents_client.get_patent(pub, include_description=False)
                if gpat_res.get("success"):
                    rec["abstract"] = gpat_res.get("abstract", "")
                    m = re.search(r'(20\d{2}|19\d{2})', pub)
                    if m:
                        rec["year"] = m.group(1)
                    bq_success = True
            except Exception as e:
                gaps.append({"pub": pub, "error": str(e)})
                
        try:
            cl1_res = await patent_get_claim1(pub, full=True)
            if cl1_res.get("success"):
                rec["claim1"] = cl1_res.get("claim1", "")
        except Exception:
            pass
            
        records.append(rec)

    payload = _json.dumps({"records": records, "gaps": gaps},
                          ensure_ascii=False, indent=2).encode("utf-8")
    entry = token_store.put_bytes(payload, "pool_records.json")
    return {
        "success": True,
        "handle": _handle(entry),
        "count": len(records),
        "gaps": gaps,
    }


# ─────────────────────────────────────────────────────────────────────
# WebDAV working-cache lifecycle tools (DD-5/DD-6/DD-7).
#
# A deliverable-cache is a subject-anchored, owner-owned token dir that the
# agent mounts over WebDAV (Basic auth) to work on bulk intermediate artifacts
# outside the container. `cache_provision` mints it + a per-owner credential;
# `cache_export` COPY-lands src + deliverables to a truth-store target (N:M);
# `cache_close` gates on working-tree cleanliness (no un-exported dirty) before
# reaping. owner_identity is threaded explicitly — NEVER silently invented
# (天條 §11 / DD-6).
# ─────────────────────────────────────────────────────────────────────
import secrets as _secrets
import shutil as _shutil
from pathlib import Path as _Path

_DAV_MOUNT_PREFIX = "/dav"


def _require_owner(owner_identity: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return a typed error envelope if owner_identity is absent (no fallback)."""
    if not owner_identity or not owner_identity.strip():
        return {
            "success": False,
            "error_code": "OWNER_REQUIRED",
            "detail": (
                "owner_identity is required and must be passed explicitly; "
                "patentmcp never infers a default/global identity (天條 §11)."
            ),
        }
    return None


@mcp.tool()
async def cache_provision(subject_id: str,
                          owner_identity: str,
                          issue_webdav_credential: bool = False) -> Dict[str, Any]:
    """Provision (idempotent) a WebDAV working cache bound to a deliverable
    subject, returning its mount path + a one-time Basic credential.

    Idempotent per (owner_identity, subject_id): calling twice returns the SAME
    cache token and mount path (a fresh credential is only minted on first
    provision; re-provision returns success without leaking the stored secret).
    The credential is returned in cleartext EXACTLY once — only its hash is
    persisted. Mount it with any WebDAV client (rclone/davfs2) using Basic auth
    username=<owner_identity> password=<credential> against the mount path.

    issue_webdav_credential (default false): R14.6 MCP-rail credential
    bootstrap (fleet standard; docxmcp reference commit 54eac2e). Holding the
    MCP socket IS the capability, so the rail may re-mint this cache's Basic
    credential without the HTTP chicken-and-egg. Opt-in ONLY: absent/false
    keeps the payload byte-identical to the prior behaviour (天條 §11 — no
    silent extra fields). WARNING: setting it ROTATES the credential — any
    existing WebDAV mount using the old password is invalidated. Set it only
    when creating or rebuilding a host mount.

    Returns {success, token, subject_id, owner_identity, mount_path,
    credential?} — `credential` present only on first provision, or whenever
    issue_webdav_credential=true.
    """
    err = _require_owner(owner_identity)
    if err:
        return err
    if not subject_id or not subject_id.strip():
        return {"success": False, "error_code": "SUBJECT_REQUIRED",
                "detail": "subject_id is required"}
    existing = token_store.find_by_subject(owner_identity, subject_id)
    entry = token_store.provision(subject_id, owner_identity)
    out = {
        "success": True,
        "token": entry.token,
        "subject_id": subject_id,
        "owner_identity": owner_identity,
        "mount_path": f"{_DAV_MOUNT_PREFIX}/{subject_id}",
    }
    if issue_webdav_credential:
        # R14.6 MCP-rail issuance: mint-or-rotate, cleartext returned ONCE.
        secret = _secrets.token_urlsafe(24)
        token_store.set_credential(entry.token, secret)
        out["credential"] = secret
    elif existing is None or not entry.credential_hash:
        secret = _secrets.token_urlsafe(24)
        token_store.set_credential(entry.token, secret)
        out["credential"] = secret
    return out


@mcp.tool(annotations=_RO)
async def cache_list(owner_identity: str) -> Dict[str, Any]:
    """List the caller's deliverable caches with their dirty state.

    Returns only caches owned by `owner_identity` (no cross-owner disclosure).
    Each item: {subject_id, token, mount_path, dirty (bool), dirty_files,
    last_export_at}.
    """
    err = _require_owner(owner_identity)
    if err:
        return err
    items = []
    for entry in token_store:
        if getattr(entry, "owner_identity", None) != owner_identity:
            continue
        if getattr(entry, "token_class", None) != "deliverable-cache":
            continue
        dirty = token_store.dirty_files(entry.token)
        items.append({
            "subject_id": entry.subject_id,
            "token": entry.token,
            "mount_path": f"{_DAV_MOUNT_PREFIX}/{entry.subject_id}",
            "dirty": bool(dirty),
            "dirty_files": dirty,
            "last_export_at": entry.last_export_at,
        })
    return {"success": True, "caches": items, "count": len(items)}


@mcp.tool()
async def cache_export(subject_id: str, target: str,
                       owner_identity: str) -> Dict[str, Any]:
    """COPY-land a cache's full working tree (src + deliverables) to a truth-store
    target reference point, then stamp the export baseline.

    N:M: the same cache may be exported to multiple targets across calls; the
    target is passed each call. `target` is a host directory reference point; it
    is created if its PARENT exists, else typed EXPORT_TARGET_UNREACHABLE (no
    directory tree is fabricated). After a successful copy, the export snapshot
    (last_export_at + per-file hashes) is recorded so `cache_close` can detect
    subsequent dirty edits.

    Returns {success, subject_id, target, files_copied} or a typed error.
    """
    err = _require_owner(owner_identity)
    if err:
        return err
    entry = token_store.find_by_subject(owner_identity, subject_id)
    if entry is None:
        return {"success": False, "error_code": "CACHE_NOT_FOUND",
                "detail": f"no cache for subject {subject_id!r} owned by caller"}
    tgt = _Path(target)
    if not tgt.parent.exists() or not tgt.parent.is_dir():
        return {
            "success": False,
            "error_code": "EXPORT_TARGET_UNREACHABLE",
            "detail": f"target parent does not exist / not writable: {tgt.parent}",
        }
    src_dir = entry.dir_path
    files_copied = 0
    try:
        tgt.mkdir(parents=True, exist_ok=True)
        for f in token_store.list_files(entry.token):
            rel = f["rel"]
            src_path = src_dir / rel
            dst_path = tgt / rel
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            _shutil.copy2(src_path, dst_path)
            files_copied += 1
    except OSError as e:
        return {"success": False, "error_code": "EXPORT_TARGET_UNREACHABLE",
                "detail": f"copy failed: {e}"}
    token_store.snapshot_exports(entry.token)
    return {"success": True, "subject_id": subject_id, "target": str(tgt),
            "files_copied": files_copied}


@mcp.tool()
async def cache_close(subject_id: str, owner_identity: str,
                      force: bool = False) -> Dict[str, Any]:
    """Close (reap) a deliverable cache, gated on working-tree cleanliness.

    If there are dirty files (changed since the last cache_export) and force is
    False, refuse with typed WORKSPACE_CLOSE_DIRTY + the un-landed file list —
    the cache is NOT reaped (天條 §11: no silent data loss). Export first, or
    pass force=True to discard. On clean (or forced) close the cache token dir is
    removed.

    Returns {success, subject_id, reaped} or a typed WORKSPACE_CLOSE_DIRTY error.
    """
    err = _require_owner(owner_identity)
    if err:
        return err
    entry = token_store.find_by_subject(owner_identity, subject_id)
    if entry is None:
        return {"success": False, "error_code": "CACHE_NOT_FOUND",
                "detail": f"no cache for subject {subject_id!r} owned by caller"}
    dirty = token_store.dirty_files(entry.token)
    if dirty and not force:
        return {
            "success": False,
            "error_code": "WORKSPACE_CLOSE_DIRTY",
            "detail": "un-exported changes exist; export first or pass force=True",
            "unlanded": dirty,
        }
    token_store.delete(entry.token)
    return {"success": True, "subject_id": subject_id, "reaped": True,
            "forced": bool(force and dirty)}


@mcp.tool()
async def patentmcp_analyze_pool(publication_numbers: List[str]) -> Dict[str, Any]:
    """[LANDED → pool_fetch (data) + skills/patentworks/scripts/pool_charts.py (charts)]

    R13 compute/landing split: the tool split into its two halves. The
    network/credential metadata fetch is now the `pool_fetch` MCP tool (returns
    a records JSON handle); the deterministic matplotlib chart rendering is the
    host-local `pool_charts.py` landing script (matplotlib precheck-fails with
    MISSING_DEPENDENCY if absent). Returns a TOOL_LANDED redirect envelope.
    """
    return {
        "success": False,
        "error_code": "TOOL_LANDED",
        "landing": {
            "script": "skills/patentworks/scripts/pool_charts.py",
            "usage": (
                "# 1) pool_fetch(publication_numbers) → download pool_records.json\n"
                "python3 skills/patentworks/scripts/pool_charts.py "
                "--in pool_records.json --out-dir charts/"
            ),
        },
    }


def __retired_analyze_pool_charts_placeholder():
    import pandas as pd
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import io
    import re
    from collections import Counter
    import math
    records = []
    gaps = []
    df = pd.DataFrame(records)
    
    # 2. Setup plotting parameters (HSL palette)
    colors = ["#004b87", "#0072ce", "#4192d9", "#7dbdf6", "#bce2f8", "#d9f0fc"]
    plt.rcParams.update({
        'figure.facecolor': 'white',
        'axes.facecolor': 'white',
        'text.color': '#333333',
        'axes.labelcolor': '#333333',
        'xtick.color': '#333333',
        'ytick.color': '#333333',
        'font.size': 10
    })
    
    charts = {}
    
    def save_chart(fig, filename):
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", dpi=150)
        plt.close(fig)
        entry = token_store.put_bytes(buf.getvalue(), filename)
        return _handle(entry)
        
    # Chart 1: Country Distribution
    fig, ax = plt.subplots(figsize=(6, 5))
    country_counts = df["country"].value_counts()
    ax.pie(country_counts, labels=country_counts.index, autopct='%1.1f%%', colors=colors[:len(country_counts)])
    ax.set_title("Patent Distribution by Country/Jurisdiction")
    charts["country"] = save_chart(fig, "country_distribution.png")
    
    # Chart 2: Years Trend
    fig, ax = plt.subplots(figsize=(7, 4.5))
    year_df = df[df["year"] != "Unknown"]
    if not year_df.empty:
        year_counts = year_df["year"].value_counts().sort_index()
        ax.plot(year_counts.index, year_counts.values, marker='o', color="#0072ce", linewidth=2.5)
        ax.fill_between(year_counts.index, year_counts.values, color="#bce2f8", alpha=0.4)
        ax.set_title("Patent Filing/Publication Trend Over Years")
        ax.set_xlabel("Year")
        ax.set_ylabel("Patent Count")
        plt.xticks(rotation=45)
    else:
        ax.text(0.5, 0.5, "No Year Data Available", ha='center', va='center')
    charts["trend"] = save_chart(fig, "years_trend.png")
    
    # Chart 3: Top 10 CPC Categories
    fig, ax = plt.subplots(figsize=(7, 5))
    all_cpcs = [cpc for cpclist in df["cpc"] for cpc in cpclist]
    if all_cpcs:
        cpc_counts = pd.Series(all_cpcs).value_counts().head(10)
        cpc_counts.plot(kind="barh", ax=ax, color="#4192d9").invert_yaxis()
        ax.set_title("Top 10 CPC Technical Classifications")
        ax.set_xlabel("Frequency")
    else:
        ax.text(0.5, 0.5, "No CPC Data Available", ha='center', va='center')
    charts["cpc"] = save_chart(fig, "cpc_distribution.png")
    
    # Chart 4: Top 10 Assignees
    fig, ax = plt.subplots(figsize=(7, 5))
    assignee_counts = df[df["assignee"] != "Unknown"]["assignee"].value_counts().head(10)
    if not assignee_counts.empty:
        assignee_counts.plot(kind="barh", ax=ax, color="#0072ce").invert_yaxis()
        ax.set_title("Top 10 Patent Assignees / Owners")
        ax.set_xlabel("Patent Count")
    else:
        ax.text(0.5, 0.5, "No Assignee Data Available", ha='center', va='center')
    charts["assignee"] = save_chart(fig, "assignee_distribution.png")
    
    # Chart 5: Category Distribution (Primary CPC Group Level, e.g. G06F, H04L)
    fig, ax = plt.subplots(figsize=(6, 5))
    cat_counts = df[df["cpc_group"] != "Unknown"]["cpc_group"].value_counts()
    if not cat_counts.empty:
        ax.pie(cat_counts, labels=cat_counts.index, autopct='%1.1f%%', colors=colors[:len(cat_counts)])
        ax.set_title("Technical Categories Distribution (CPC Group)")
    else:
        ax.text(0.5, 0.5, "No Category Data Available", ha='center', va='center')
    charts["category"] = save_chart(fig, "category_distribution.png")
    
    # Chart 6: Pure-Matplotlib Word Cloud (Key Tech Features)
    fig, ax = plt.subplots(figsize=(8, 8))
    ax.axis("off")
    
    stopwords = {"system", "device", "method", "apparatus", "plurality", "comprising", "comprises", "associated", 
                 "herein", "having", "first", "second", "one", "invention", "patents", "patent", "disclosed", 
                 "discloses", "disclosure", "data", "information", "user", "plural", "methods", "devices", "systems",
                 "一種", "方法", "裝置", "系統", "複數", "包含", "設有", "包括", "提供", "根據", "本發明", "申請", "實施", "公開",
                 "技術", "主要", "特徵", "進行", "其係", "該當", "以及", "藉由", "本實施例", "具有", "第一", "第二", "步驟", "單元",
                 "訊號", "模組", "控制", "處理", "接收", "發送"}
                 
    text_pool = ""
    for _, row in df.iterrows():
        text_pool += f" {row['title']} {row['abstract']} {row['claim1']}"
        
    words = []
    eng_words = re.findall(r'\b[a-zA-Z]{3,}\b', text_pool)
    words.extend([w.lower() for w in eng_words if w.lower() not in stopwords])
    zh_words = re.findall(r'[\u4e00-\u9fa5]{2,4}', text_pool)
    words.extend([w for w in zh_words if w not in stopwords])
    
    word_counts = Counter(words).most_common(50)
    
    if word_counts:
        max_freq = word_counts[0][1]
        boxes = []
        hsl_colors = ["#004b87", "#0072ce", "#4192d9", "#2a7ebb", "#58a4d8", "#005a9c"]
        
        for idx, (word, freq) in enumerate(word_counts):
            fontsize = int(12 + 28 * (math.log(freq) / math.log(max_freq) if max_freq > 1 else 1))
            theta = 0.0
            placed = False
            a = 0.005
            
            is_zh = any('\u4e00' <= char <= '\u9fa5' for char in word)
            width = len(word) * fontsize * (0.0055 if is_zh else 0.0032)
            height = fontsize * 0.014
            
            for _ in range(800):
                r = a * theta
                x = 0.5 + r * math.cos(theta)
                y = 0.5 + r * math.sin(theta)
                
                box = (x - width/2, y - height/2, x + width/2, y + height/2)
                if box[0] < 0.05 or box[2] > 0.95 or box[1] < 0.05 or box[3] > 0.95:
                    theta += 0.05
                    continue
                    
                overlap = False
                for b in boxes:
                    if not (box[2] < b[0] or box[0] > b[2] or box[3] < b[1] or box[1] > b[3]):
                        overlap = True
                        break
                        
                if not overlap:
                    color = hsl_colors[idx % len(hsl_colors)]
                    ax.text(x, y, word, fontsize=fontsize, color=color, ha='center', va='center', weight='bold')
                    boxes.append(box)
                    placed = True
                    break
                    
                theta += 0.08
                
            if not placed:
                ax.text(0.1 + (idx * 0.05) % 0.8, 0.05 + (idx * 0.07) % 0.9, word, 
                        fontsize=fontsize//2, color="#7dbdf6", ha='center', va='center')
                        
        ax.set_title("Patent Pool Key Technical Features Word Cloud", fontsize=12, pad=20)
    else:
        ax.text(0.5, 0.5, "No Text Data Available for Word Cloud", ha='center', va='center')
        
    charts["wordcloud"] = save_chart(fig, "wordcloud.png")
    
    return {
        "success": True,
        "charts": charts,
        "gaps": gaps
    }


@mcp.tool()
async def search_audit(
    matrix_log_path: str,
    campaign_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Machine-checkable RIGOR GATE for the priorsearch flow — audits whether a
    search was BROAD ENOUGH, so a thin "checked a few hits and called it done"
    search cannot pass off as a complete landscape.

    Reads a campaign's `matrix-log.jsonl` (one query per line; schema in
    priorsearch.md §0) and scores breadth against floor thresholds (design DD-2):
      - min_class_anchors=3   distinct class codes across IPC/CPC
      - min_concept_groups=3  distinct campaign concept groups (A-E) touched
      - min_jurisdictions=3   TW + CN + US all searched
      - min_boolean_combos=2  at least 2 boolean shapes (not all SINGLE-word dragnet)
      - min_queries=12         minimum cartesian coverage

    `00_campaign.md` may RAISE any floor (never lower) and may declare an explicit
    jurisdiction exclusion with a reason via an HTML-comment marker, e.g.:
      <!-- audit: min_queries=20 exclude_jurisdiction=TW reason="TW low value" -->

    This tool issues NO network requests and runs NO searches — it only audits the
    evidence the search agent left behind. Returns a verdict envelope:
      {verdict: PASS|WARN|FAIL, coverage{...}, thresholds{...}, gaps[...],
       warnings[...], per_jurisdiction{...}, per_database{...},
       applied_overrides{...}, evidence{...}}

    FAIL ⇒ the search is too thin to deliver: fix the listed gaps and re-search
    before producing the pool / report (priorsearch.md §3.B step 4 & §3.D step 8).

    [LANDED → skills/patentworks/scripts/search_audit.py]

    R13 compute/landing split: this rigor gate issues NO network requests — it
    only audits the local matrix-log.jsonl the search agent left behind, so it
    runs as a host-local landing script. Returns a TOOL_LANDED redirect envelope.
    """
    return {
        "success": False,
        "error_code": "TOOL_LANDED",
        "landing": {
            "script": "skills/patentworks/scripts/search_audit.py",
            "usage": (
                "python3 skills/patentworks/scripts/search_audit.py "
                "--log matrix-log.jsonl [--campaign 00_campaign.md]"
            ),
        },
    }


@mcp.tool()
async def patentdb_put(
    publication_number: str,
    fields: Optional[Dict[str, Any]] = None,
    blobs: Optional[Dict[str, Any]] = None,
    acquisition_cost: Optional[str] = None,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """Upsert ONE patent's bibliographic record into the global patentdb structured layer.

    patentdb is a PASSIVELY-ACCUMULATED, cost-weighted, cross-project bibliographic
    store (sqlite). Records are SPARSE by design — a patent may enter with only a
    pubno + title, fields filled in progressively over time. Upsert is a PROGRESSIVE
    MERGE: existing non-empty values are kept (COALESCE), only NULL fields are filled,
    unless overwrite=true.

    Only bibliographic FACTS live here — NO per-project screening/relevance scores
    (those stay in the project's candidates.csv).

    Args:
        publication_number: e.g. "US20230081319A1" / "TWI854998B" / "CN120543023A".
        fields: bibliographic field subset — any of: title_orig, title_en, abstract,
            claim1, applicants, inventors, application_no, application_date,
            publication_date, priority_date, cpc_codes, ipc_codes, family_id, kind.
        blobs: {"pdf":{"path","sha256"}, "xml":{"path","sha256"},
            "figures":[{"name","path","sha256"}]} — file-system paths only.
        acquisition_cost: coarse cost tier "high"/"low"/"free" (DD-9). Mark "high" for
            data fetched from BigQuery/EPO/consented-scraping so it is never re-fetched.
        overwrite: when true, incoming non-empty values replace existing ones.

    Returns:
        {pubno, action: created|updated|unchanged, merged_fields?, completeness}.

    [LANDED → skills/patentworks/scripts/patentdb_local.py put]
    """
    return {
        "success": False,
        "error_code": "TOOL_LANDED",
        "landing": {
            "script": "skills/patentworks/scripts/patentdb_local.py",
            "usage": (
                "python3 skills/patentworks/scripts/patentdb_local.py put "
                "--pubno US20230081319A1 --fields fields.json"
            ),
        },
    }


@mcp.tool(annotations=_RO)
async def patentdb_query(
    publication_number: Optional[str] = None,
    fts: Optional[str] = None,
    country: Optional[str] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """Query the global patentdb bibliographic store (NO project/screening dimension).

    This is the LIBRARY-SIDE entry for "腳踏兩條船" (DD-12): while analysing a case
    from its own search files, ALSO query patentdb for relevant targets the current
    search did not surface — cross-project accumulation may already hold a prior-art
    hit that nails this case, saving fresh API quota.

    Modes (pass exactly one primary filter):
        publication_number: exact lookup → full record + completeness flags.
        fts: full-text search over title/abstract/claim1. ≥3 chars uses FTS5 (trigram,
            CJK-aware); <3 chars (e.g. 2-char CJK term) falls back to LIKE scan.
        country: TW/US/CN/EP/WO — list recent records for that jurisdiction.
        (no filter): most-recent records + total count.

    Returns include `completeness` flags so the caller can judge whether to go fetch
    missing pieces (passive accumulation: fetch only what's missing).

    [LANDED → skills/patentworks/scripts/patentdb_local.py query]
    """
    return {
        "success": False,
        "error_code": "TOOL_LANDED",
        "landing": {
            "script": "skills/patentworks/scripts/patentdb_local.py",
            "usage": (
                "python3 skills/patentworks/scripts/patentdb_local.py query "
                "--fts 'solid state battery' --country TW --limit 20"
            ),
        },
    }


@mcp.tool()
async def patentdb_import_csv(csv_path: str) -> Dict[str, Any]:
    """Bulk-import BIBLIOGRAPHIC fields from a candidates.csv into patentdb.

    Imports ONLY bibliographic columns (pubno/title/abstract/claim1/cpc/family/dates);
    per-project screening columns (relevance/score/tech_gist/reason) are IGNORED — they
    stay in the project CSV (DD-2). Each row → progressive-merge upsert (DD-4). The whole
    file is wrapped in a single transaction (DD-10, million-scale friendly).

    Default trigger is INLINE from the search tool when a CSV lands (DD-11); this manual
    tool is the back-fill entry for historical CSVs.

    [LANDED → skills/patentworks/scripts/patentdb_local.py import-csv]
    """
    return {
        "success": False,
        "error_code": "TOOL_LANDED",
        "landing": {
            "script": "skills/patentworks/scripts/patentdb_local.py",
            "usage": (
                "python3 skills/patentworks/scripts/patentdb_local.py import-csv "
                "--csv candidates.csv"
            ),
        },
    }


# =====================================================================
# GPSS4 member-area 標記清單 (project-folder) tools
# /plans/patentmcp_gpss4-folder-tools DD-2..DD-5 (verified 2026-07-11)
# Session-based web-app auth (TTS* cookies, md5-lookup CAPTCHA login, SSO
# meta-refresh). Distinct from patent_search (the REST search ladder).
# =====================================================================


@mcp.tool()
async def gpss4_folder_list() -> Dict[str, Any]:
    """List the patents currently in the GPSS4 member 標記清單 (mark list).

    Logs into the TIPO GPSS4 web app (GPSS4_USERNAME / GPSS4_PASSWORD from env)
    and returns the marked patents. The mark list is GPSS4's project-folder
    surface. Read-only.

    NOTE: GPSS4 renders the mark list synchronously in the add-to-marks response;
    a standalone list fetch via the expired-slot home link returns an empty shell
    (DD-5 trap). If no marks exist yet, returns an empty list.
    """
    from patent_mcp_server.gpss4.folder import GPSS4Folder, GPSS4FolderError

    f = GPSS4Folder()
    try:
        # A same-session marked-list read: mark-list content is produced by the
        # add-to-marks response; with no pending selection this surfaces the
        # current list. We expose it via a no-op search+list on the member area.
        ml = await f.current_marks()
        return {"success": True, **ml.to_dict()}
    except GPSS4FolderError as e:
        return {"success": False, "error_code": "GPSS4_FOLDER", "error": str(e)}
    finally:
        await f.close()


@mcp.tool()
async def gpss4_folder_mark(number: str, axis: str = "pub") -> Dict[str, Any]:
    """Add a patent to the GPSS4 member 標記清單 by number.

    axis='pub' searches by 公開/公告號 (@PN); axis='apply' by 申請號 (@AN).
    Runs the full 3-step sequence (number search -> clickselect -> add to marks)
    and returns the resulting mark list. WRITE operation (modifies the member
    account's marks).
    """
    from patent_mcp_server.gpss4.folder import GPSS4Folder, GPSS4FolderError

    f = GPSS4Folder()
    try:
        ml = await f.mark_patent(number, axis=axis)
        return {"success": True, "marked": number, **ml.to_dict()}
    except GPSS4FolderError as e:
        return {"success": False, "error_code": "GPSS4_FOLDER", "error": str(e)}
    finally:
        await f.close()


@mcp.tool(annotations=_RO)
async def gpss4_folder_search(number: str, axis: str = "pub") -> Dict[str, Any]:
    """Run a GPSS4 number search (member area) WITHOUT marking. Read-only.

    axis='pub' (@PN, 公開/公告號) or 'apply' (@AN, 申請號). Returns the hit count
    and the selectable hits (db/rec/curt tuples). Use gpss4_folder_mark to add.
    """
    from patent_mcp_server.gpss4.folder import GPSS4Folder, GPSS4FolderError

    f = GPSS4Folder()
    try:
        res = await f.search_number(number, axis=axis)
        return {
            "success": True,
            "count": res.count,
            "hits": [{"db": d, "rec": r, "curt": c} for d, r, c in res.hits],
        }
    except GPSS4FolderError as e:
        return {"success": False, "error_code": "GPSS4_FOLDER", "error": str(e)}
    finally:
        await f.close()


# ---------------------------------------------------------------------------
# GPSS4 member-area 進階檢索 (advanced-search) harvest tool
# /plans/patentmcp_gpss4-folder-tools DD-7..DD-11 (verified 2026-07-11)
# Quota-free: drives the logged-in web 進階檢索 (no API daily-download cap),
# harvests the full result list INCLUDING patent-family grouping.
# ---------------------------------------------------------------------------
@mcp.tool(annotations=_RO)
async def gpss4_advanced_search(
    query: str,
    max_pages: int = 200,
    expand_family: bool = True,
    delivery: str = "token",
    owner_identity: str = "",
    subject_id: str = "",
    csv_rel: str = "pool.csv",
    csv_path: str = "",
) -> Dict[str, Any]:
    """Harvest the TIPO GPSS4 web 進階檢索 (advanced search) result list into a
    family-tagged patent pool, delivered via patentmcp's standard file rails.

    Drives the LOGGED-IN web advanced search (GPSS4_USERNAME / GPSS4_PASSWORD
    from env) as a PURE-HTTPX state machine (no browser), bypassing the
    official API's daily download quota. Returns every result row with title +
    abstract, and — crucially — patent-family grouping for trustworthy dedup.

    query:  GPSS advanced-search syntax (field codes, NOT `TI=`):
            title `(詞)@TI`, abstract `(詞)@AB`, claims `(詞)@CL`,
            classification `CS=G06F-0003/00`, date `AD=2006:2007`; combine
            with AND/OR. e.g. `(video)@TI AND CS=H04N-0021/00`.
    max_pages: HIGH safety cap on pages to paginate (default 200 = ~10k rows;
            50 rows/page is the 進階檢索 max, no 100/page option). NOT a batch
            size — harvest walks EVERY page into ONE complete pool. If a result
            set exceeds max_pages the return carries truncated=true (pool is
            partial; raise max_pages), never a silent cut.
    expand_family: click 家族收合 so each row carries its family_group id
            (the `N.M` family-sequence key). Set False to skip (faster, no
            per-row family binding, but the summary family_count is still
            returned).

    File delivery (choose ONE via `delivery`):
      * "token" (DEFAULT): the pool CSV bytes land in the docxmcp-compatible
        token store; the response carries a download handle
        {token, rel, download_url, sha256} — fetch via /files/{token}/blob/{rel},
        exactly like every other patentmcp artifact tool. No path needed.
      * "cache": land the CSV into the caller's WebDAV deliverable-cache for the
        given subject. Requires owner_identity + subject_id (the cache is
        provisioned idempotently if absent). The CSV appears at
        <mount>/`csv_rel` over the mounted WebDAV tree; export later with
        cache_export. owner_identity is NEVER inferred (天條 §11).
      * "none": JSON only — every patent row still carries family_group +
        is_family_representative; no file is written.
    csv_rel: filename inside the token dir / cache (default "pool.csv").
    csv_path: LEGACY escape hatch — an absolute container path to also write
            the CSV to (back-compat; prefer token/cache delivery).

    Family dedup (NON-DESTRUCTIVE): every row is kept and tagged with
    is_family_representative — True for the family member with the EARLIEST
    apply_date (ties broken by pat_no), False for the rest. To get a
    one-per-family deduped list, filter patents on is_family_representative.

    Returns {success, total, family_count, representative_count,
             summary_family_count, pages_fetched, total_pages, patents[],
             + delivery handle}:
      * delivery="token" -> token, rel, download_url, bytes, sha256
      * delivery="cache" -> cache_token, subject_id, mount_path, csv_rel,
                            credential? (first provision only)
      * csv_path echoed back when the legacy path was also written.
      * family_count = ACTUAL distinct family groups parsed post-collapse
        (authoritative for dedup); equals representative_count.
      * summary_family_count = the pre-collapse estimate the page prints.
      * GPSS gives 簡易專利家族 grouping, NOT INPADOC family-ID strings.
    """
    import csv as _csv
    import io as _io
    from patent_mcp_server.gpss4.adv_search import harvest, GPSS4AdvSearchError

    def _csv_bytes(result: Dict[str, Any]) -> bytes:
        """Render the pool as UTF-8-BOM CSV bytes (same cols as write_csv)."""
        fields = ["seq", "pat_no", "apply_date", "title", "abstract",
                  "family_group", "is_family_representative"]
        buf = _io.StringIO()
        w = _csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for p in result.get("patents", []):
            w.writerow(p)
        return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")

    if delivery not in ("token", "cache", "none"):
        return {"success": False, "error_code": "GPSS4_ADV_BAD_DELIVERY",
                "error": f"delivery must be token|cache|none, got {delivery!r}"}
    if delivery == "cache":
        err = _require_owner(owner_identity)
        if err:
            return err
        if not subject_id or not subject_id.strip():
            return {"success": False, "error_code": "SUBJECT_REQUIRED",
                    "detail": "delivery='cache' requires subject_id"}

    try:
        res = await harvest(
            query, max_pages=max_pages, expand_family=expand_family,
        )
    except GPSS4AdvSearchError as e:
        return {"success": False, "error_code": "GPSS4_ADV_SEARCH", "error": str(e)}
    except Exception as e:
        return {"success": False, "error_code": "GPSS4_ADV_SEARCH_RUNTIME",
                "error": f"{type(e).__name__}: {e}"}

    out: Dict[str, Any] = {"success": True, **res}
    data = _csv_bytes(res)

    if delivery == "token":
        entry = token_store.put_bytes(data, csv_rel)
        out.update(_handle(entry, csv_rel))
    elif delivery == "cache":
        existing = token_store.find_by_subject(owner_identity, subject_id)
        entry = token_store.provision(subject_id, owner_identity)
        token_store.write_file(entry.token, csv_rel, data)
        out["cache_token"] = entry.token
        out["subject_id"] = subject_id
        out["mount_path"] = f"{_DAV_MOUNT_PREFIX}/{subject_id}"
        out["csv_rel"] = csv_rel
        out["bytes"] = len(data)
        if existing is None or not getattr(entry, "credential_hash", None):
            secret = _secrets.token_urlsafe(24)
            token_store.set_credential(entry.token, secret)
            out["credential"] = secret

    if csv_path:  # legacy escape hatch, additive
        from patent_mcp_server.gpss4.adv_search import write_csv
        out["csv_path"] = write_csv(res, csv_path)
    return out


def main():
    import argparse

    parser = argparse.ArgumentParser(prog="patent-mcp-server")
    parser.add_argument(
        "--transport", choices=["stdio", "http"],
        default=os.environ.get("PATENTS_TRANSPORT", "stdio"),
        help="stdio (default) for local spawn; http for UDS/TCP gateway service.",
    )
    parser.add_argument("--uds", default=os.environ.get("PATENTS_UDS"),
                        help="Unix domain socket path (http transport; preferred).")
    parser.add_argument("--host", default=os.environ.get("PATENTS_HOST", "127.0.0.1"))
    # --port default None: transport set is decided by which flags are present
    # (--uds and/or --port). UDS-only, TCP-only, and dual are all valid (R1.2).
    parser.add_argument(
        "--port", type=lambda v: int(v) if v not in (None, "") else None,
        default=(int(os.environ["PATENTS_PORT"]) if os.environ.get("PATENTS_PORT") else None),
        help="TCP port (additional/outward transport; omit for UDS-only).",
    )
    parser.add_argument("--export-claims", help="Comma-separated patent numbers to batch retrieve Claim 1 (standalone CLI mode).")
    parser.add_argument("--output", help="Optional output JSON path for the exported claims.")
    args = parser.parse_args()

    if args.export_claims:
        import asyncio
        import json
        patent_numbers = [x.strip() for x in args.export_claims.split(",") if x.strip()]
        
        async def run_export():
            results = {}
            for pub in patent_numbers:
                try:
                    res = await patent_get_claim1(pub, full=True)
                    results[pub] = res
                except Exception as e:
                    results[pub] = {"success": False, "publication_number": pub, "error": str(e)}
                await asyncio.sleep(0.5)
            
            data = json.dumps(results, indent=2, ensure_ascii=False).encode("utf-8")
            entry = token_store.put_bytes(data, "claims.json")
            handle = _handle(entry)
            
            output_data = {
                "success": True,
                "claims": results,
                "token": handle["token"],
                "rel": handle["rel"],
                "download_url": handle["download_url"],
                "bytes": handle["bytes"],
                "sha256": handle["sha256"]
            }
            
            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    json.dump(output_data, f, indent=2, ensure_ascii=False)
                print(f"Exported claims saved to {args.output}")
            else:
                print(json.dumps(output_data, indent=2, ensure_ascii=False))
                
        asyncio.run(run_export())
        return

    if args.transport == "http":
        from patent_mcp_server import _http_app
        logger.info("Starting patentmcp with http transport")
        _http_app.serve(mcp, token_store, uds=args.uds, host=args.host, port=args.port)
        return

    # stdio: start the docxmcp-style blob server (background thread) for files.
    base = _file_server.start_file_server(token_store)
    if base:
        logger.info(f"File blob server on {base} (/files/{{token}}/blob/{{rel}})")
    logger.info("Starting USPTO Patent MCP server with stdio transport")
    mcp.run(transport='stdio')

if __name__ == "__main__":
    main()
