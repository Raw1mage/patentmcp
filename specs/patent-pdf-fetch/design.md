# Design: Patent PDF & Figure Retrieval

## Context
Existing `patentmcp` tools focus on text (abstracts, claims, description) but lack a reliable binary PDF acquisition path. Session evidence proves that Google Storage guessed paths are 403, while hashed paths from `citation_pdf_url` work.

## Goals / Non-Goals
- **Goals**: Unified `fetch_patent_pdf` tool, EPO OPS Image support, Google citation fallback.
- **Non-Goals**: Keyword search on Google Patents, broad crawling, OCR implementation.

## Risks / Trade-offs
- **Risk**: Google Patents page access may trigger 429/503.
- **Mitigation**: Conservative pacing, official-first priority, early-exit on block.

## Critical Files
- `vendor/patents-mcp/src/patent_mcp_server/epo/client.py`: EPO binary support.
- `vendor/patents-mcp/src/patent_mcp_server/gpatents/client.py`: Citation resolver.
- `vendor/patents-mcp/src/patent_mcp_server/patents.py`: Tool exposure.

## Decisions
- **DD-1**: Google Patents page access is permitted only as a last-resort, small-volume, known-publication resolver for `citation_pdf_url`; it is not a search backend.
- **DD-2**: EPO OPS images is the primary planned legal/official route because existing `EPOClient` already has OAuth and throttle handling.
- **DD-3**: Do not infer Google PDF URLs. Always resolve the true hashed URL from the page or another verified source.
