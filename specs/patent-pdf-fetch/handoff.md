# Handoff: Patent PDF Fetch

## Execution Contract
This implementation follows the `patent-pdf-fetch` plan. The goal is to provide a unified `fetch_patent_pdf` tool in `patents.py` that routes requests to EPO OPS first, then falls back to Google Patents metadata resolution for explicit known publication numbers. Binary results MUST be stored in the MCP `token-store` and never returned in-band.

## Required Reads
- `vendor/patents-mcp/src/patent_mcp_server/epo/client.py`: For EPO client extension.
- `vendor/patents-mcp/src/patent_mcp_server/gpatents/client.py`: For Google citation resolver.
- `vendor/patents-mcp/src/patent_mcp_server/patents.py`: For tool exposure.
- `specs/architecture.md`: For delivery contract alignment.

## Stop Gates In Force
- Stop if EPO OPS image endpoint requires different auth than existing biblio/search.
- Stop if Google Patents access returns 429/503 repeatedly after cooldown.
- Stop if any implementation suggests broad search crawling.

## Execution-Ready Checklist
- [ ] EPO Consumer Key/Secret are available in environment.
- [ ] `token-store` path is correctly configured and writable.
- [ ] BS4 (BeautifulSoup) is available for HTML parsing.

## Downstream Consumer: docxmcp
The primary consumer of this tool's output is `docxmcp_document(action="decompose", format="pdf")`.
- **Handoff Variable**: `pdf.token` or `pdf.rel`.
