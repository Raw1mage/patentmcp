# Proposal: patent-pdf-fetch

## Why

- PatentWorks can retrieve claims, bibliographic data, abstracts, and full text through official/legal APIs, but it still lacks a reliable **known publication number → original patent PDF handle** workflow.
- Prior-art landscape reports need representative figures and source PDFs for shortlist patents. Without a first-class PDF fetch tool, agents either stop at text-only evidence or misuse broad Google Patents scraping tools.
- Session evidence showed the missing step is not binary storage: once the true Google Patents `citation_pdf_url` is known, `gpatents_download_pdf` can download the PDF successfully. The gap is a governed resolver/downloader workflow with official-first routing and Google Patents as a last-resort single-record fallback.

## Original Requirement Wording (Baseline)

- "直接跨repo開plan改patentmcp"
- "原plan走合法路線的做法仍需plan"
- "Google Patents ... 在『針對已知專利』進行下載的行為下，應該可以小量使用。"

## Requirement Revision History

- 2026-06-26: initial draft created via plan-init.ts
- 2026-06-26: clarified that Google Patents `citation_pdf_url` extraction is a **last resort** for shortlist / known publication numbers only; the primary design must still prefer legal/official routes such as EPO OPS images where available.

## Effective Requirement Description

1. Add a patentmcp workflow/tool surface that fetches an original patent PDF for a **known publication number** and stores it as a token/blob handle, without returning binary bytes through model context.
2. Route through legal/official sources first, especially EPO OPS images when coverage allows; use Google Patents page `citation_pdf_url` extraction only as a governed final fallback for small, explicit shortlist items.
3. Preserve priorsearch workflow discipline: bulk prior-art search remains GPSS/BigQuery/official API based; Google Patents page access is not a search engine and must never be used for broad crawling.
4. Make the result compatible with downstream docxmcp PDF decomposition (`docxmcp_document(action="decompose", format="pdf", path=...)`) so representative figures can be extracted into report packages.

## Scope

### IN
- EPO OPS images endpoint support: discover available image/PDF pages and download page/full-image PDFs into token storage.
- Google Patents single-record resolver: known publication number → patent page → `citation_pdf_url` → existing binary downloader.
- A public MCP tool API that exposes source routing, status, bytes/hash, token handle, and provenance.
- Safety gates: no broad keyword crawling, no parallel Google page scraping, strict per-call known-publication input, early-exit on cooldown/503/429.
- Tests or smoke scripts covering URL extraction and successful tokenized PDF download using known safe examples.

### OUT
- Broad Google Patents search crawling or batch result scraping.
- Legal determination of fair use / ToS beyond implementing the approved small known-record fallback boundary.
- Full TIPO OpenData bulk TIFF ingestion/indexing; this remains a future TW-specific pipeline.
- OCR/figure semantic analysis; downstream docxmcp decomposition may extract pages/images, but this plan only guarantees PDF acquisition and handle compatibility.

## Non-Goals

- Do not replace GPSS / BigQuery / EPO / USPTO text retrieval tools.
- Do not make Google Patents the default prior-art search backend.
- Do not infer Google Storage PDF URLs from publication numbers; true hashed URLs must be read from `citation_pdf_url` or another verified source.

## Constraints

- Binary outputs must go to token/blob storage, never model context.
- Official/legal routes are preferred over web-page fallback.
- Google Patents access is restricted to explicit known publication numbers and small shortlist volumes; rate limiting must be conservative and observable.
- Existing `EPOClient` already owns OAuth, token refresh, single-flight pacing, and 403/429 cooldown handling; new EPO image methods should reuse that infrastructure.
- Current `google_*` BigQuery tools provide text only and do not expose PDF/image URLs.

## What Changes

- Extend `vendor/patents-mcp/src/patent_mcp_server/epo/client.py` with image metadata and PDF page/full-image download support.
- Add a governed Google Patents citation PDF resolver/downloader path for known publication numbers.
- Add/modify MCP tools in `vendor/patents-mcp/src/patent_mcp_server/patents.py` to expose a unified PDF fetch function and lower-level source-specific helpers if needed.
- Update `skills/patentworks/reference/priorsearch/pdf-figure-extraction.md` after implementation to replace temporary endpoint notes with the verified workflow.

## Capabilities

### New Capabilities
- `known publication → PDF handle`: acquire an original patent PDF and return token metadata.
- `official-first source routing`: try EPO OPS images when applicable before Google Patents fallback.
- `Google citation URL fallback`: resolve `citation_pdf_url` from a known patent page and download the hashed PDF URL.
- `docxmcp-ready handoff`: expose local/token handle suitable for PDF decomposition and figure extraction.

### Modified Capabilities
- `gpatents_download_pdf`: remains a raw URL downloader, but the new workflow should supply verified hashed URLs instead of guessed `/pdfs/<PN>.pdf` URLs.
- `epo_*`: expands from family/biblio/search to include image/PDF retrieval.

## Impact

- `vendor/patents-mcp/src/patent_mcp_server/epo/client.py`
- `vendor/patents-mcp/src/patent_mcp_server/patents.py`
- token-store / handle contract used by existing `gpatents_download_pdf`
- `skills/patentworks/reference/priorsearch/pdf-figure-extraction.md`
- downstream priorsearch report work folders under `03_assets/patents/` and docxmcp report packages under `04_report/`
