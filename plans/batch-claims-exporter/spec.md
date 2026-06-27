# Spec: Batch Claims Exporter

## Purpose
Establish a robust, compliant batch patent independent claims (Claim 1) exporter. It prioritizes official API sources (TIPO GPSS, USPTO PPUBS, EPO OPS) over Google Patents scraper, integrates EPO claims retrieval, and delivers results in a tokenized JSON format compatible with `docxmcp` as well as a standalone CLI tool.

## Requirements

### Requirement: TIPO-First and Official Fallback Routing
For any given patent, the system MUST prioritize TIPO (GPSS) for TW, US, and CN. If it fails or is other jurisdictions, it MUST fall back to official APIs (USPTO PPUBS for US, EPO OPS for EP, BigQuery for others) before using Google Patents scraper as a last resort.

#### Scenario: TW patent query
- Given a TW patent number `TW202403664A`.
- When `patent_get_claim1` is called.
- Then the system queries TIPO (GPSS) first.

#### Scenario: US patent query fallback
- Given a US patent number `US11875659B2`.
- When TIPO (GPSS) query fails or is skipped.
- Then the system queries USPTO (PPUBS) next, then EPO, then BigQuery, and only uses Google Patents if all else fail.

### Requirement: EPO claims integration
The system MUST support retrieving claims from the EPO Open Patent Services (OPS) API.

#### Scenario: Query EP claims
- Given an EP patent number `EP1000000A1` (docdb `EP.1000000.A1`).
- When `EPOClient.claims` is called.
- Then the system fetches from `/published-data/publication/docdb/EP.1000000.A1/claims` and parses the BadgerFish JSON to extract Claim 1.

### Requirement: Batch claims retrieval tool
The system MUST provide an MCP tool `ppubs_batch_get_claims` to fetch Claim 1 for multiple patents and save the resulting JSON in the token store.

#### Scenario: Batch fetch
- Given a list of patent numbers `["US20250252737A1", "TW202403664A"]`.
- When `ppubs_batch_get_claims` is called.
- Then Claim 1 for each is fetched, combined into a JSON mapping, staged in the token store, and a token handle is returned.

### Requirement: CLI Export
The system MUST support batch claims export via command-line arguments.

#### Scenario: CLI invocation
- Given the CLI command `python -m patent_mcp_server --export-claims "US20250252737A1,TW202403664A"`.
- When executed.
- Then the system prints the output JSON or token handle to stdout.

## Acceptance Checks
- [ ] Querying `TW` patent uses TIPO GPSS directly.
- [ ] `EPOClient.claims` parses and extracts Claim 1 successfully from EPO JSON.
- [ ] `ppubs_batch_get_claims` tool returns success, a JSON mapping of claims, and a valid token store handle (`token`, `rel`, `download_url`).
- [ ] Running with `--export-claims` outputs the JSON mapped claims to stdout or `--output` file.
