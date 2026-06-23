"""
USPTO Patent Search MCP Server

This file provides a Model Context Protocol (MCP) server that exposes tools for interacting with multiple USPTO APIs:

1. ppubs.uspto.gov - Provides full text patent documents, PDF downloads, and advanced search
2. api.uspto.gov - Provides metadata, continuity information, transactions, and assignments

The server uses stdio transport for command-line tools, following the MCP standard.
"""
import os
import json
import logging
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
from patent_mcp_server.google.bigquery_client import GoogleBigQueryClient
from patent_mcp_server.gpatents.client import GooglePatentsClient
from patent_mcp_server.gpss.client import GPSSClient, GPSSCondition
from patent_mcp_server.epo.client import EPOClient
from patent_mcp_server._token_store import default_store
from patent_mcp_server import _file_server
from patent_mcp_server import screening_table as _st
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

# =====================================================================
# Unified USPTO Patents Tool
# =====================================================================

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
        patent_number: For ppubs_get_patent_by_number/ppubs_download_patent_pdf: Patent number
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
        if not guid or not source_type:
            return {"error": True, "message": "guid and source_type parameters are required for ppubs_get_full_document"}
        return await ppubs_client.get_document(guid, source_type)

    elif method == "ppubs_get_patent_by_number":
        if not patent_number:
            return {"error": True, "message": "patent_number parameter is required for ppubs_get_patent_by_number"}

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
            logger.info(f"Found patent: {patent.get('guid')}")
        elif result.get("docs") and len(result["docs"]) > 0:
            patent = result["docs"][0]
            logger.info(f"Found patent: {patent.get('guid')}")
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
async def google_search_patents(
    query: str,
    country: str = GooglePatentsCountries.US,
    limit: int = Defaults.SEARCH_LIMIT,
    offset: int = 0,
    start_date: Optional[int] = None,
    end_date: Optional[int] = None,
) -> Dict[str, Any]:
    """Search Google Patents Public Datasets using BigQuery

    Searches patent titles and abstracts for the specified query string.
    Returns patent publication number, title, abstract, dates, inventors,
    assignees, and classification codes.

    Args:
        query: Search query string (searches titles and abstracts)
        country: Country code (US, EP, WO, JP, CN, KR, GB, DE, FR, CA, AU)
        limit: Maximum number of results to return (default: 100, max: 500)
        offset: Number of results to skip for pagination (default: 0)
        start_date: Optional start date for publication_date filter (YYYYMMDD format, e.g., 20220101)
        end_date: Optional end date for publication_date filter (YYYYMMDD format, e.g., 20251231)

    Returns:
        Dictionary containing search results with patent metadata
    """
    if limit > Defaults.SEARCH_LIMIT_MAX:
        return ApiError.validation_error(
            f"Limit cannot exceed {Defaults.SEARCH_LIMIT_MAX}", "limit"
        )

    if country not in GooglePatentsCountries.ALL:
        return ApiError.validation_error(
            f"Invalid country code. Must be one of: "
            f"{', '.join(GooglePatentsCountries.ALL)}",
            "country",
        )

    try:
        result = await google_bq_client.search_patents(
            query, country, limit, offset, start_date, end_date
        )
        return result
    except Exception as e:
        logger.error(f"Error searching Google Patents: {str(e)}")
        return ApiError.create(
            message=f"Failed to search Google Patents: {str(e)}",
            status_code=500
        )


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
    except Exception as e:
        logger.error(
            f"Error fetching description for {publication_number}: {str(e)}"
        )
        return ApiError.create(
            message=f"Failed to fetch description: {str(e)}", status_code=500
        )


@mcp.tool()
async def google_search_by_inventor(
    inventor_name: str,
    country: str = GooglePatentsCountries.US,
    limit: int = Defaults.SEARCH_LIMIT,
    offset: int = 0,
    start_date: Optional[int] = None,
    end_date: Optional[int] = None,
) -> Dict[str, Any]:
    """Search Google Patents by inventor name

    Finds patents where the specified inventor is listed. Useful for tracking
    an inventor's patent portfolio.

    Args:
        inventor_name: Inventor name to search for
        country: Country code (US, EP, WO, JP, CN, KR, GB, DE, FR, CA, AU)
        limit: Maximum number of results to return (default: 100, max: 500)
        offset: Number of results to skip for pagination (default: 0)
        start_date: Optional start date for publication_date filter (YYYYMMDD format, e.g., 20220101)
        end_date: Optional end date for publication_date filter (YYYYMMDD format, e.g., 20251231)

    Returns:
        Dictionary containing search results
    """
    if limit > Defaults.SEARCH_LIMIT_MAX:
        return ApiError.validation_error(
            f"Limit cannot exceed {Defaults.SEARCH_LIMIT_MAX}", "limit"
        )

    if country not in GooglePatentsCountries.ALL:
        return ApiError.validation_error(
            f"Invalid country code. Must be one of: "
            f"{', '.join(GooglePatentsCountries.ALL)}",
            "country",
        )

    try:
        result = await google_bq_client.search_by_inventor(
            inventor_name, country, limit, offset, start_date, end_date
        )
        return result
    except Exception as e:
        logger.error(f"Error searching by inventor: {str(e)}")
        return ApiError.create(
            message=f"Failed to search by inventor: {str(e)}", status_code=500
        )


@mcp.tool()
async def google_search_by_assignee(
    assignee_name: str,
    country: str = GooglePatentsCountries.US,
    limit: int = Defaults.SEARCH_LIMIT,
    offset: int = 0,
    start_date: Optional[int] = None,
    end_date: Optional[int] = None,
) -> Dict[str, Any]:
    """Search Google Patents by assignee/company name

    Finds patents assigned to a specific company or organization. Useful for
    analyzing a company's patent portfolio.

    Args:
        assignee_name: Assignee/company name to search for
        country: Country code (US, EP, WO, JP, CN, KR, GB, DE, FR, CA, AU)
        limit: Maximum number of results to return (default: 100, max: 500)
        offset: Number of results to skip for pagination (default: 0)
        start_date: Optional start date for publication_date filter (YYYYMMDD format, e.g., 20220101)
        end_date: Optional end date for publication_date filter (YYYYMMDD format, e.g., 20251231)

    Returns:
        Dictionary containing search results
    """
    if limit > Defaults.SEARCH_LIMIT_MAX:
        return ApiError.validation_error(
            f"Limit cannot exceed {Defaults.SEARCH_LIMIT_MAX}", "limit"
        )

    if country not in GooglePatentsCountries.ALL:
        return ApiError.validation_error(
            f"Invalid country code. Must be one of: "
            f"{', '.join(GooglePatentsCountries.ALL)}",
            "country",
        )

    try:
        result = await google_bq_client.search_by_assignee(
            assignee_name, country, limit, offset, start_date, end_date
        )
        return result
    except Exception as e:
        logger.error(f"Error searching by assignee: {str(e)}")
        return ApiError.create(
            message=f"Failed to search by assignee: {str(e)}", status_code=500
        )


@mcp.tool()
async def google_search_by_cpc(
    cpc_code: str,
    country: str = GooglePatentsCountries.US,
    limit: int = Defaults.SEARCH_LIMIT,
    offset: int = 0,
    start_date: Optional[int] = None,
    end_date: Optional[int] = None,
) -> Dict[str, Any]:
    """Search Google Patents by CPC classification code

    Finds patents with the specified Cooperative Patent Classification (CPC) code.
    Useful for finding patents in specific technology areas.

    Args:
        cpc_code: CPC code to search for (e.g., G06N3/08 for neural networks)
        country: Country code (US, EP, WO, JP, CN, KR, GB, DE, FR, CA, AU)
        limit: Maximum number of results to return (default: 100, max: 500)
        offset: Number of results to skip for pagination (default: 0)
        start_date: Optional start date for publication_date filter (YYYYMMDD format, e.g., 20220101)
        end_date: Optional end date for publication_date filter (YYYYMMDD format, e.g., 20251231)

    Returns:
        Dictionary containing search results
    """
    if limit > Defaults.SEARCH_LIMIT_MAX:
        return ApiError.validation_error(
            f"Limit cannot exceed {Defaults.SEARCH_LIMIT_MAX}", "limit"
        )

    if country not in GooglePatentsCountries.ALL:
        return ApiError.validation_error(
            f"Invalid country code. Must be one of: "
            f"{', '.join(GooglePatentsCountries.ALL)}",
            "country",
        )

    try:
        result = await google_bq_client.search_by_cpc(
            cpc_code, country, limit, offset, start_date, end_date
        )
        return result
    except Exception as e:
        logger.error(f"Error searching by CPC code: {str(e)}")
        return ApiError.create(
            message=f"Failed to search by CPC code: {str(e)}", status_code=500
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
        conditions: List[GPSSCondition] = []
        if cpc:
            conditions.append(GPSSCondition("CS", cpc))
        if keyword:
            conditions.append(GPSSCondition("TI/AB", keyword))
        if date_from or date_to:
            conditions.append(GPSSCondition("ID", f"{date_from or ''}:{date_to or ''}"))
        res = await gpss_client.search(
            conditions=conditions, databases=databases,
            fields="PN,AN,ID,AD,PR,TI,AB,CL,IC,CS,UC,PA,IN",
            num=max(num, max_rows), fmt="json",
        )
        if not res.get("success") and res.get("error"):
            return {"success": False, "error": res["error"]}
        records = _st.gpss_to_records(res)
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
    """
    try:
        data = await gpatents_client.fetch_bytes(figure_url)
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": str(e)}
    name = filename or figure_url.rsplit("/", 1)[-1] or "figure.png"
    entry = token_store.put_bytes(data, name)
    return _handle(entry)


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
    parser.add_argument("--port", type=int, default=int(os.environ.get("PATENTS_PORT", "8078")))
    args = parser.parse_args()

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
