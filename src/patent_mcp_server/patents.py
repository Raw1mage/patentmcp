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
        "Source priority: GPSS (gpss_search, primary) > EPO (epo_family / "
        "epo_biblio / epo_search) > Google Patents (gpatents_*, rate-limited) > "
        "BigQuery (cheap metadata only). Tool results return file handles; "
        "bytes are delivered via /files/{token}/blob/{rel}, not through context."
    ),
)

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
    - ppubs_search_patents: Search granted patents in USPTO Public Search
    - ppubs_search_applications: Search published patent applications
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
        query: For ppubs_search_*: Search query string using USPTO syntax
        start: For ppubs_search_*: Starting position for results (default: 0)
        limit: For ppubs_search_*/search_*: Maximum results to return (default: 100/25)
        sort: For ppubs_search_*/search_*: Sort order
        default_operator: For ppubs_search_*: Default operator AND/OR (default: OR)
        expand_plurals: For ppubs_search_*: Include plural forms (default: True)
        british_equivalents: For ppubs_search_*: Include British spellings (default: True)
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

    # Route to the appropriate method
    if method == "ppubs_search_patents":
        if not query:
            return {"error": True, "message": "query parameter is required for ppubs_search_patents"}
        return await ppubs_client.run_query(
            query=query,
            start=start,
            limit=limit,
            sort=sort,
            default_operator=default_operator,
            sources=["USPAT"],
            expand_plurals=expand_plurals,
            british_equivalents=british_equivalents
        )

    elif method == "ppubs_search_applications":
        if not query:
            return {"error": True, "message": "query parameter is required for ppubs_search_applications"}
        return await ppubs_client.run_query(
            query=query,
            start=start,
            limit=limit,
            sort=sort,
            default_operator=default_operator,
            sources=["US-PGPUB"],
            expand_plurals=expand_plurals,
            british_equivalents=british_equivalents
        )

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

@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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

@mcp.tool()
async def gpatents_search(
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


def _save_local_patent_cache(country: str, norm_pat: str, file_type: str, data: bytes) -> None:
    import json
    import time
    
    db_root = _get_db_root()
    target_dir = db_root / country / norm_pat
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = f"specification.{file_type}"
        (target_dir / filename).write_bytes(data)
        
        # Write simple metadata.json if not present
        meta_path = target_dir / "metadata.json"
        if not meta_path.is_file():
            meta_data = {
                "publication_number": f"{country}{norm_pat}",
                "normalized_number": norm_pat,
                "country": country,
                "cached_at": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            meta_path.write_text(json.dumps(meta_data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to save local patent cache for {country}/{norm_pat}: {e}")


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
    filename: str = "screening.csv",
) -> Dict[str, Any]:
    """Run a CPC-anchored search and LAND the candidate set as a human-readable
    CSV in the token store — the raw rows never flow through the model context.
    The agent then reads the CSV in batches, judges each row, and writes back
    the AI columns (relevance/score/tech_gist/feat/reason).

    Columns are selectable (欄位隨選制): a mandatory core (專利號/申請號/名稱/摘要/
    獨立項/家族) is always kept; `purpose` adds a preset group
    (landscape→分類; priorart→日期+CPC; fto→日期+申請人+法律狀態; minimal→無);
    `extra_fields`/`exclude_fields` fine-tune. AI columns are always appended.

    Source: GPSS when GPSS_USER_CODE is set (fills all columns), else Google
    Patents (partial — no claim1/cpc/appno/family from search; those land blank).

    Returns {success, handle{token,rel,download_url,...}, count, deduped, source,
    columns, gaps} — or {success, too_broad, count, suggestion} when the hit
    count exceeds max_rows (narrow the query; do not analyze a divergent set).
    """
    # 1) search → normalized records
    if gpss_client.configured():
        import asyncio
        conditions: List[GPSSCondition] = []
        if cpc:
            conditions.append(GPSSCondition("CS", cpc))
        if keyword:
            conditions.append(GPSSCondition("TI/AB", keyword))
        if date_from or date_to:
            conditions.append(GPSSCondition("ID", f"{date_from or ''}:{date_to or ''}"))
        
        target_num = max(num, max_rows)
        chunk_size = 50
        records = []
        skip = 0
        
        while len(records) < target_num:
            current_num = min(chunk_size, target_num - len(records))
            res = await gpss_client.search(
                conditions=conditions, databases=databases,
                fields="PN,AN,ID,AD,PR,TI,AB,CL,IC,CS,UC,PA,IN",
                num=current_num, skip=skip, fmt="json",
            )
            if not res.get("success"):
                if len(records) > 0:
                    logger.warning(
                        "GPSS search pagination failed at skip=%d: %s",
                        skip, res.get("error") or res.get("message")
                    )
                    break
                return {"success": False, "error": res.get("error") or res.get("message") or "GPSS search failed"}
            
            page_records = _st.gpss_to_records(res)
            if not page_records:
                break
            records.extend(page_records)
            
            total_available = res.get("total")
            if total_available is not None:
                try:
                    total_available = int(total_available)
                except ValueError:
                    total_available = None
            
            if total_available is not None and len(records) >= total_available:
                break
                
            skip += len(page_records)
            await asyncio.sleep(1.0)
            
        source = "gpss"
    else:
        q = keyword or cpc or ""
        if not q:
            return {"success": False, "error": "need cpc or keyword"}
        res = await gpatents_client.search(
            query=q, countries=None, num=min(num, 100),
            before=(f"publication:{date_to}" if date_to else None),
            after=(f"publication:{date_from}" if date_from else None),
        )
        if not res.get("success"):
            return {"success": False, "error": res.get("error", "search failed")}
        records = _st.google_to_records(res.get("results", []))
        source = "google"

    count = len(records)
    # 2) >max_rows → don't produce a table; ask to narrow
    if count > max_rows:
        return {
            "success": True, "too_broad": True, "count": count, "source": source,
            "suggestion": f"命中 {count} 件 > {max_rows};請收斂(加嚴 CPC 子群 / 加關鍵詞 / 縮日期)後再建表。",
        }

    # 3) dedup by family → select columns → CSV → handle
    deduped = _st.dedup_by_family(records)
    columns = _st.resolve_columns(purpose, extra_fields, exclude_fields)
    data = _st.build_csv(deduped, columns)
    entry = token_store.put_bytes(data, filename)
    gaps = {k: v for k, v in _st.KNOWN_GAPS.items()
            if (k in columns or k == "family")
            and (source == "google" or k in ("legal_status", "citations"))}
    return {
        "success": True,
        "handle": _handle(entry),
        "count": count,
        "deduped": len(deduped),
        "source": source,
        "purpose": purpose,
        "columns": [_st.COLUMNS[k] for k in columns],
        "gaps": gaps,
    }


@mcp.tool()
async def stage_file(path: str, filename: Optional[str] = None) -> Dict[str, Any]:
    """Stage an existing local file (e.g. a scored CSV the screening flow built)
    into the token store, returning a docxmcp-style handle
    {token, rel, download_url, bytes, sha256} for the client to download or for
    docxmcp `from_token` to pull into a report. The bytes never pass through the
    model context.
    """
    if not os.path.isfile(path):
        return {"success": False, "error": f"not a file: {path}"}
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as e:
        return {"success": False, "error": str(e)}
    name = filename or os.path.basename(path)
    entry = token_store.put_bytes(data, name)
    return _handle(entry)


@mcp.tool()
async def gpatents_get(
    publication_number: str,
    include_description: bool = False,
) -> Dict[str, Any]:
    """Fetch a patent's full abstract + claims from its Google Patents page.

    WARNING: Google Patents is highly sensitive to scraping. Use ONLY as a last resort
    for single-file retrieval. DO NOT use for batch processing or automated crawling.
    
    Use after gpatents_search to pull the complete claims (the search snippet is
    only an excerpt). CN/JP/etc. are returned as Google's English machine
    translation. abstract + claims are returned in-band (small). When
    include_description=True the large full text is instead LANDED in the token
    store and the response carries a download handle (token/rel/download_url),
    NOT the description bytes.
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


def clean_html_text(html_text: str) -> str:
    if not html_text:
        return ""
    import re
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', ' ', html_text)
    # Normalize whitespaces
    return re.sub(r'\s+', ' ', text).strip()

def extract_claim1_text(claims_text: str, full: bool = True) -> str:
    if not claims_text:
        return "Claim 1 not found."
    claims_text = claims_text.strip()
    import re
    
    text = None
    for pattern in [
        r'1\.\s+(.*?)(?=\s+2\.\s+|\n2\.)',
        r'1\.\s+(.*)',
        r'1[\.、](.*?)(?=\s*2[\.、]|\n2[\.、])',
        r'1[\.、](.*)'
    ]:
        m = re.search(pattern, claims_text, re.DOTALL | (re.IGNORECASE if '2' in pattern else 0))
        if m:
            text = re.sub(r'\s+', ' ', m.group(1).strip())
            break
            
    if text is None:
        text = claims_text.strip()
        
    if not full and len(text) > 1000:
        return text[:1000].strip() + "..."
    return text

@mcp.tool()
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


@mcp.tool()
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

    Pass the `pdf_url` from a gpatents_search result. Returns a docxmcp-style
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

    Pass the `representative_figure_url` from a gpatents_search result. Returns a
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
    """
    import tempfile
    import os as _os

    pub = publication_number or patent_number
    if not pub:
        return {"success": False, "error": "MISSING_PUBLICATION_NUMBER",
                "detail": "publication_number (or patent_number alias) is required"}
    publication_number = pub

    # Step 1: ensure a PDF (reuse the unified fetch tool + its fallback chain).
    # This is a figure-extraction purpose: GPSS headless scraping IS authorized
    # here (TW figure pipeline), so opt into the explicit scraping gate.
    pdf_res = await fetch_patent_pdf(publication_number, allow_scraping=True)
    if not pdf_res.get("success"):
        return {"success": False, "error": "NO_PDF",
                "publication_number": publication_number,
                "detail": pdf_res.get("error"), "attempts": pdf_res.get("attempts")}

    # Resolve the landed PDF to an on-disk path (poppler needs a filesystem
    # path). blob_path returns the real file inside the token namespace.
    try:
        src_pdf_path = str(token_store.blob_path(pdf_res["token"], pdf_res["rel"]))
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": "NO_PDF",
                "publication_number": publication_number,
                "detail": f"fetched PDF token could not be resolved: {e}"}

    with tempfile.TemporaryDirectory() as td:
        # Copy into a private temp path so a TTL reap mid-render can't pull it.
        pdf_path = _os.path.join(td, "patent.pdf")
        import shutil as _shutil
        _shutil.copyfile(src_pdf_path, pdf_path)

        # Step 2: locate the figure page.
        loc = _locate_figure_page(pdf_path)
        if loc["page"] is None:
            # Grade the failure: a PDF with embedded images but no FIG.1 text
            # marker is likely a no-text-layer scan that still holds figures —
            # surface that honestly instead of a flat NO_FIGURE_PAGE. Do NOT
            # guess which embedded image is the representative figure.
            image_count = _pdf_image_count(pdf_path)
            if image_count > 0:
                return {"success": False, "error": "NO_FIGURE_PAGE_BUT_IMAGES_PRESENT",
                        "publication_number": publication_number,
                        "image_count": image_count,
                        "pages": loc.get("pages"),
                        "detail": (f"PDF 無 FIG.1 文字標記(可能為無文字層掃描版),"
                                   f"但含 {image_count} 個內嵌影像;請人工挑選或從已下載 PDF 抽圖"),
                        "source_pdf": {"source": pdf_res.get("source"),
                                       "provenance": pdf_res.get("provenance")}}
            return {"success": False, "error": "NO_FIGURE_PAGE",
                    "publication_number": publication_number,
                    "pages": loc.get("pages"),
                    "detail": "No FIG.1 marker and no usable text layer "
                              "(likely a scanned PDF without OCR)."}

        # Step 3: render the page.
        png = _render_page_png(pdf_path, loc["page"], dpi=dpi)
        if not png:
            return {"success": False, "error": "RENDER_FAILED",
                    "publication_number": publication_number,
                    "page_number": loc["page"]}

    name = f"{publication_number}_FIG_p{loc['page']}.png"
    entry = token_store.put_bytes(png, name)
    result = _handle(entry)
    result["page_number"] = loc["page"]
    result["dpi"] = dpi
    result["locate_method"] = loc["method"]
    result["source_pdf"] = {"source": pdf_res.get("source"),
                            "provenance": pdf_res.get("provenance")}
    return result


@mcp.tool()
async def gpss_download_representative_figure(
    publication_number: str,
) -> Dict[str, Any]:
    """Download a patent's representative figure headlessly from TIPO GPSS into the token store.

    This replicates a browser session to fetch the static representative figure.
    Returns a handle {token, rel, download_url, bytes, sha256} of the saved image.

    BR_20260628 A: serialized through _GPSS_POLICY (Concurrency=1 + random
    pacing + cooldown parking), so parallel calls cannot trip Cloudflare's
    Managed Challenge on tiponet.tipo.gov.tw.
    """
    async with _GPSS_POLICY.guard():
        return await _gpss_download_representative_figure_impl(publication_number)


async def _gpss_download_representative_figure_impl(
    publication_number: str,
    session_client=None,
) -> Dict[str, Any]:
    """Scrape one TW representative figure. NO lock here — the caller (the tool
    wrapper or _GpssScrapeSession.fetch_*) owns _GPSS_SCRAPE_LOCK + pacing.

    session_client: when provided, reuse this persistent client (cookie jar /
    cf_clearance continuity across a batch); when None, a throwaway client is
    created and closed for this single scrape.
    """
    import re

    pat = publication_number.strip()
    
    try:
        async with _gpss_client(session_client) as client:
            # Step 1: Visit portal
            await client.get("https://tiponet.tipo.gov.tw/030_OUT_V1/home.do")
            
            # Step 2: Initialize GPSS session
            await client.get("https://tiponet.tipo.gov.tw/gpss2/")
            
            # Step 3: Load search page and bypass client-side JS random redirect
            rand_val = random.random()
            gpss_url = f"https://tiponet.tipo.gov.tw/gpss2/gpsskmc/gpssbkm?@@{rand_val}"
            res = await client.get(gpss_url)
            
            # Extract INFO parameter
            m_info = re.search(r'name=["\']?INFO["\']?\s+value=["\']?([A-Za-z0-9]+)["\']?', res.text, re.IGNORECASE)
            if not m_info:
                m_info = re.search(r'value=["\']?([A-Za-z0-9]+)["\']?\s+name=["\']?INFO["\']?', res.text, re.IGNORECASE)
                
            if not m_info:
                return {"success": False, "error": "Failed to retrieve INFO token from GPSS session"}
            
            info_val = m_info.group(1)
            
            # Extract action path
            m_action = re.search(r'action=["\']?(/gpss[12]/gpsskmc/gpssbkm[^\'"]*)["\']?', res.text, re.IGNORECASE)
            action_path = m_action.group(1) if m_action else '/gpss2/gpsskmc/gpssbkm'
            action_url = f"https://tiponet.tipo.gov.tw{action_path}"
            
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
                    redirect_url = f"https://tiponet.tipo.gov.tw/gpss2/gpsskmc/{redirect_url}"
                res = await client.get(redirect_url)
            
            # Step 5: Follow detail page link
            m_detail = re.search(r'href=["\']?(/gpss[12]/gpsskmc/gpssbkm\?[^\s\'">]+)[^>]*class=["\']?link02["\']?', res.text, re.IGNORECASE)
            if not m_detail:
                return {"success": False, "error": f"Patent detail link for '{pat}' not found in search results"}
                
            detail_url = f"https://tiponet.tipo.gov.tw{m_detail.group(1)}"
            res_detail = await client.get(detail_url)
            
            # Extract image URLs
            img_urls = re.findall(r'/gpss[12]/gpssbkmusr/[^\'" >]+', res_detail.text)
            img_urls = [url.split()[0] for url in img_urls]
            img_urls = list(dict.fromkeys(img_urls))
            
            # Find representative figure (TWG1)
            rep_img_url = None
            for url in img_urls:
                if "TWG1" in url:
                    rep_img_url = url
                    break
            if not rep_img_url and img_urls:
                rep_img_url = img_urls[0]
                
            if not rep_img_url:
                return {"success": False, "error": "No representative figure found for this patent"}
                
            abs_img_url = f"https://tiponet.tipo.gov.tw{rep_img_url}"
            
            # Step 6: Fetch image bytes
            img_res = await client.get(abs_img_url)
            if img_res.status_code != 200:
                return {"success": False, "error": f"Failed to download image (HTTP {img_res.status_code})"}
                
            # Put bytes to token store
            filename = rep_img_url.rsplit("/", 1)[-1] or f"{pat}_figure.png"
            entry = token_store.put_bytes(img_res.content, filename)
            return _handle(entry)
            
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
            
            # Step 2: Initialize GPSS session
            await client.get("https://tiponet.tipo.gov.tw/gpss2/")
            
            # Step 3: Load search page and bypass client-side JS random redirect
            rand_val = random.random()
            gpss_url = f"https://tiponet.tipo.gov.tw/gpss2/gpsskmc/gpssbkm?@@{rand_val}"
            res = await client.get(gpss_url)
            
            # Extract INFO parameter
            m_info = re.search(r'name=["\']?INFO["\']?\s+value=["\']?([A-Za-z0-9]+)["\']?', res.text, re.IGNORECASE)
            if not m_info:
                m_info = re.search(r'value=["\']?([A-Za-z0-9]+)["\']?\s+name=["\']?INFO["\']?', res.text, re.IGNORECASE)
                
            if not m_info:
                return {"success": False, "error": "Failed to retrieve INFO token from GPSS session"}
            
            info_val = m_info.group(1)
            
            # Extract action path
            m_action = re.search(r'action=["\']?(/gpss[12]/gpsskmc/gpssbkm[^\'"]*)["\']?', res.text, re.IGNORECASE)
            action_path = m_action.group(1) if m_action else '/gpss2/gpsskmc/gpssbkm'
            action_url = f"https://tiponet.tipo.gov.tw{action_path}"
            
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
                    redirect_url = f"https://tiponet.tipo.gov.tw/gpss2/gpsskmc/{redirect_url}"
                res = await client.get(redirect_url)
            
            # Step 5: Follow detail page link
            m_detail = re.search(r'href=["\']?(/gpss[12]/gpsskmc/gpssbkm\?[^\s\'">]+)[^>]*class=["\']?link02["\']?', res.text, re.IGNORECASE)
            if not m_detail:
                return {"success": False, "error": f"Patent detail link for '{pat}' not found in search results"}
                
            detail_url = f"https://tiponet.tipo.gov.tw{m_detail.group(1)}"
            res_detail = await client.get(detail_url)
            
            # Step 6: Find PDF links (harder calls) in detail page
            harder_links = re.findall(r"harder\s*\(\s*this\s*,\s*['\"]([^'\"]+)['\"]", res_detail.text)
            if not harder_links:
                return {"success": False, "error": "No PDF document download links found in patent detail page"}
                
            # Filter and choose the best link
            selected_path = None
            for path in harder_links:
                if "TWBA" in path or "TWBP" in path:
                    selected_path = path
                    break
            if not selected_path:
                selected_path = harder_links[0]
                
            # Step 7: Request the intermediate HTML page for the selected PDF
            pdf_page_url = f"https://tiponet.tipo.gov.tw{selected_path}"
            res_pdf_page = await client.get(pdf_page_url)
            
            # Extract the actual PDF file path from this HTML page
            m_pdf = re.search(r'/gpss[12]/gpssbkmusr/[^\'" >]+\.pdf', res_pdf_page.text, re.IGNORECASE)
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
            
            # Step 2: Initialize GPSS session
            await client.get("https://tiponet.tipo.gov.tw/gpss2/")
            
            # Step 3: Load search page and bypass client-side JS random redirect
            rand_val = random.random()
            gpss_url = f"https://tiponet.tipo.gov.tw/gpss2/gpsskmc/gpssbkm?@@{rand_val}"
            res = await client.get(gpss_url)
            
            # Extract INFO parameter
            m_info = re.search(r'name=["\']?INFO["\']?\s+value=["\']?([A-Za-z0-9]+)["\']?', res.text, re.IGNORECASE)
            if not m_info:
                m_info = re.search(r'value=["\']?([A-Za-z0-9]+)["\']?\s+name=["\']?INFO["\']?', res.text, re.IGNORECASE)
                
            if not m_info:
                return {"success": False, "error": "Failed to retrieve INFO token from GPSS session"}
            
            info_val = m_info.group(1)
            
            # Extract action path
            m_action = re.search(r'action=["\']?(/gpss[12]/gpsskmc/gpssbkm[^\'"]*)["\']?', res.text, re.IGNORECASE)
            action_path = m_action.group(1) if m_action else '/gpss2/gpsskmc/gpssbkm'
            action_url = f"https://tiponet.tipo.gov.tw{action_path}"
            
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
                    redirect_url = f"https://tiponet.tipo.gov.tw/gpss2/gpsskmc/{redirect_url}"
                res = await client.get(redirect_url)
            
            # Step 5: Follow detail page link
            m_detail = re.search(r'href=["\']?(/gpss[12]/gpsskmc/gpssbkm\?[^\s\'">]+)[^>]*class=["\']?link02["\']?', res.text, re.IGNORECASE)
            if not m_detail:
                return {"success": False, "error": f"Patent detail link for '{pat}' not found in search results"}
                
            detail_url = f"https://tiponet.tipo.gov.tw{m_detail.group(1)}"
            res_detail = await client.get(detail_url)
            
            # Step 6: Find harder links in detail page
            harder_links = re.findall(r"harder\s*\(\s*this\s*,\s*['\"]([^'\"]+)['\"]", res_detail.text)
            if not harder_links:
                return {"success": False, "error": "No document download links found in patent detail page"}
                
            # Filter and choose the TW_GX link (Full-text XML)
            selected_path = None
            for path in harder_links:
                if "TW_GX" in path:
                    selected_path = path
                    break
            if not selected_path:
                return {"success": False, "error": f"TW_GX (Full-text XML) download link for '{pat}' not found in detail page"}
                
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
                    res_gpss["source"] = src
                    res_gpss["provenance"] = {"api": "TIPO GPSS headless session",
                                              "scraping": True}
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

    return await gpss_client.search(
        conditions=conditions,
        databases=databases,
        case_type=case_type,
        patent_type=patent_type,
        fields=fields or "PN,ID,TI,IN,PA,AB,CS,CL",
        num=num or 30,
        skip=skip or 0,
        fmt="json",
    )


# =====================================================================
# EPO OPS Tools — official INPADOC family / biblio / CQL search
# =====================================================================

@mcp.tool()
async def epo_family(publication_number: str) -> Dict[str, Any]:
    """Get the INPADOC patent family for a publication via EPO OPS (official).

    Unifies the US/CN/TW/EP/JP members of one invention into a single family —
    more reliable than BigQuery's split family_id. Pass any member's number
    (e.g. "US11213256B2"); returns {family_id, count, members:[pub numbers]}.
    Use to deduplicate a screening pool by true family or to expand a seed.
    """
    return await epo_client.family(publication_number)


@mcp.tool()
async def epo_biblio(publication_number: str) -> Dict[str, Any]:
    """Get official bibliographic data + abstract for a publication via EPO OPS.

    Fills the abstract/title/applicant/IPC for patents that Google/BigQuery
    couldn't supply in-band. Returns {title, abstract, applicants, ipc}.
    """
    return await epo_client.biblio(publication_number)


@mcp.tool()
async def epo_search(cql: str, range: str = "1-25") -> Dict[str, Any]:
    """Search EPO OPS published data with a CQL query (official, global).

    CQL examples: 'pa=faceheart' (applicant), 'in=poh' (inventor),
    'txt=photoplethysmography and ic=A61B5/024' (text + IPC), 'pn=US11213256'.
    `range` paginates (e.g. "1-25", "26-50"; max 100/page, 2000 total).
    Returns {total, count, results:[publication numbers]}.
    """
    return await epo_client.search(cql, range_=range)


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
async def patentmcp_analyze_pool(publication_numbers: List[str]) -> Dict[str, Any]:
    """Analyze a patent pool and generate 6 high-quality HSL-themed visualization charts
    (Country, Trend, CPC, Assignee, Category, and pure-matplotlib Word Cloud)
    staged in the token store.
    """
    import pandas as pd
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import io
    import re
    from collections import Counter
    import math
    
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
      - min_class_anchors=3   distinct class codes across IPC/CPC/USPC
      - min_concept_groups=3  distinct campaign concept groups (A-E) touched
      - min_jurisdictions=3   TW + CN + US all searched
      - min_boolean_combos=2  at least 2 boolean shapes (not all SINGLE-word dragnet)
      - uspc_required=True     US search must include >=1 USPC-anchored query
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
    """
    try:
        result = _sa.audit(matrix_log_path, campaign_path)
        result["success"] = True
        return result
    except _sa.MatrixLogError as e:
        return {
            "success": False,
            "error": str(e),
            "hint": "matrix-log.jsonl 必須存在且為每行一筆 JSON 查詢紀錄（schema 見 priorsearch.md §0）。",
        }


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
