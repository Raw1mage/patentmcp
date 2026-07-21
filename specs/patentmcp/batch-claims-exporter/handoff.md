# Handoff: Batch Claims Exporter

## Execution Contract
This implementation follows the `batch-claims-exporter` plan. The goal is to provide a batch claims exporter tool and CLI, optimize routing to prioritize TIPO GPSS, and implement EPO claims query.

## Required Reads
- `src/patent_mcp_server/epo/client.py`: Implementation of `EPOClient`.
- `src/patent_mcp_server/patents.py`: Tool definitions and server CLI parser.

## Stop Gates In Force
- Stop if EPO OPS API credentials are not set in `.env` (bypass or skip EPO fallback if not configured).
- Stop if TIPO GPSS user code is missing (cannot run GPSS first-priority queries).

## Execution-Ready Checklist
- [ ] GPSS_USER_CODE and EPO credentials are verified in `.env`.
- [ ] Pytest environment is active and running tests.
