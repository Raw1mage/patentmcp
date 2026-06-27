# Design: Batch Claims Exporter

## Context
Existing patent claim extraction has two main flaws: it queries Google Patents first or second, risking scraper blocks (403/503), and it lacks a high-level batch interface. We need to implement a TIPO-first routing logic, integrate EPO claims API, and package these into a batch MCP tool and CLI exporter.

## Goals / Non-Goals
- **Goals**:
  - Implement TIPO-first (GPSS) routing for TW, US, and CN patents.
  - Implement EPO OPS claims retrieval API in `EPOClient` and parse its BadgerFish JSON output.
  - Add `ppubs_batch_get_claims` tool returning both mapping and staged token store handle.
  - Add `--export-claims` and `--output` options to CLI.
- **Non-Goals**:
  - Rewriting existing PDF downloading or full text description extraction routing.
  - Adding external XML parser libraries unless native python xml/json parsing is insufficient (Python's native JSON/dict parsing is sufficient since EPO OPS returns BadgerFish JSON).

## Risks / Trade-offs
- **Risk**: EPO API throttling (OPS allows 15 searches/min, but metadata/claims retrieval limits vary).
  - **Mitigation**: Reuse `EPOClient` pacing lock (`self._req_lock`) and automatic 403/429 backoff retry loops.
- **Risk**: TIPO GPSS connection timeout or slow queries.
  - **Mitigation**: Add try-except fallback to next source in the chain.

## Critical Files
- `src/patent_mcp_server/epo/client.py`: Adds `claims()` function and BadgerFish parsing.
- `src/patent_mcp_server/patents.py`: Optimizes `patent_get_claim1` fallback chain, implements `ppubs_batch_get_claims` MCP tool, and exposes CLI options in `main()`.

## Decisions
- **DD-1 (TIPO-First)**: GPSS databases will be routed as `["TWA", "TWB"]` for TW, `["USA", "USB"]` for US, and `["CNA", "CNB"]` for CN. TIPO GPSS will always be queried first for these three jurisdictions.
- **DD-2 (EPO Claims Endpoint)**: `EPOClient.claims` will make a GET request to `/published-data/publication/docdb/{docdb}/claims` with `Accept: application/json`.
- **DD-3 (BadgerFish Parsing)**: The claim extraction from BadgerFish JSON will search:
  `data -> ops:world-patent-data -> exchange-documents -> exchange-document -> claims -> claim` (which is a list or single object).
  For each claim, it checks `@num`. If `@num == "1"`, it extracts the `claim-text` (recursively cleaning any nested elements/strings) and returns it.
- **DD-4 (CLI Standalone Mode)**: CLI claims export will run outside the stdio/http server daemon if `--export-claims` is provided, preventing port binding conflicts and exit immediately on completion.
