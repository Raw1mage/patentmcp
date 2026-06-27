# Tasks: patent-pdf-fetch

## T1 — EPO OPS images route

- [x] T1.1 Add an EPO binary GET helper that reuses OAuth, pacing, and 403/429 cooldown handling.
- [x] T1.2 Implement image metadata lookup for `/published-data/publication/docdb/{docdb}/images`.
- [x] T1.3 Implement PDF page/full-image download for `/published-data/images/{CC}/{NUM}/{KIND}/fullimage.pdf?Range=N`.
- [x] T1.4 Return token-store handles and structured `not_found` / `throttled` / `unsupported` errors.

## T2 — Google Patents citation fallback

- [x] T2.1 Implement known-publication page fetch for `https://patents.google.com/patent/{PN}/en` with conservative timeout and UA.
- [x] T2.2 Parse `citation_pdf_url` from HTML and reject guessed `/pdfs/<PN>.pdf` paths.
- [x] T2.3 Download the resolved hashed PDF URL through the existing token-store byte path.
- [x] T2.4 Add early-exit behavior for 429/503/timeouts and expose the cooldown/blocked state in attempts metadata.

## T3 — Unified MCP tool

- [x] T3.1 Add `fetch_patent_pdf(publication_number, sources?, filename?, include_attempts?)` to `patents.py`.
- [x] T3.2 Route official sources first (`epo_images`), then Google citation fallback only if enabled/default policy allows.
- [x] T3.3 Return source, attempts, provenance, bytes/hash, token, rel, and download URL.
- [x] T3.4 Ensure no binary bytes are returned in model context.

## T4 — Tests and smoke checks

- [x] T4.1 Add parser fixture test for Google `citation_pdf_url` extraction.
- [x] T4.2 Add unit tests for source routing and structured failures.
- [x] T4.3 Add smoke command/documentation for TWI854998B and one EPO-covered publication.
- [x] T4.4 Verify downloaded PDF can be handed to docxmcp PDF decomposition.

## T5 — Documentation sync

- [x] T5.1 Update `skills/patentworks/reference/priorsearch/pdf-figure-extraction.md` with final tool names and source priority.
- [x] T5.2 Update `skills/patentworks/flows/priorsearch.md` if the work folder asset contract changes.
- [x] T5.3 Sync `specs/architecture.md` module boundary notes for PDF/figure/fulltext handles.
- [x] T5.4 Record event log with verification results and remaining source limitations.
