# Tasks: batch-claims-exporter

## T1 — EPO Client Claims Integration
- [x] T1.1 Add `claims(pub)` method to `EPOClient` in `src/patent_mcp_server/epo/client.py`.
- [x] T1.2 Implement BadgerFish JSON parser in `claims()` to extract Claim 1 text (under `@num="1"`).
- [x] T1.3 Add error handling for 404/not found or empty response cases from EPO API.

## T2 — Route Optimization & Fallback Chain
- [x] T2.1 Modify `patent_get_claim1` in `src/patent_mcp_server/patents.py` to query TIPO (GPSS) first for TW, US, and CN patents.
- [x] T2.2 Set fallback sequence: TIPO (GPSS) -> USPTO (PPUBS) / EPO (OPS) / BigQuery -> Google Patents Scraper.
- [x] T2.3 Ensure Google Patents scraper is strictly the last resort.

## T3 — Batch Claims MCP Tool
- [x] T3.1 Expose `ppubs_batch_get_claims(patent_numbers)` as an MCP tool.
- [x] T3.2 Implement pacing/rate limiting loop when calling `patent_get_claim1` sequentially.
- [x] T3.3 Stage the output JSON claims mapping in the `token_store` and return the standard docxmcp token handle.

## T4 — CLI Claims Exporter
- [x] T4.1 Expose `--export-claims` and `--output` arguments in `main()` of `src/patent_mcp_server/patents.py`.
- [x] T4.2 Direct the CLI flow to bypass stdio/http server daemon if `--export-claims` is specified.
- [x] T4.3 Save or print output JSON mapped claims to the designated path or stdout.

## T5 — Verification & Tests
- [x] T5.1 Write unit tests in `tests/` to verify `EPOClient.claims` parsing and TIPO-first routing logic.
- [x] T5.2 Perform standalone CLI run test and check the staged file in `token_store`.
