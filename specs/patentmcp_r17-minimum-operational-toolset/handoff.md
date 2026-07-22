# Handoff: patentmcp_r17-minimum-operational-toolset

## Execution Contract

- Deliver R17 conformance for patentmcp by closing the three recon-confirmed gaps:
  A1 `resources/read` portable egress, A2 structured capability summary, A3 typed
  asset preflight + content assertions. Done = all tasks.md checked, full pytest
  suite green, R17.6 end-to-end eval passing on both floors (portable + WebDAV),
  standard §12 matrix R17 column updated, architecture synced, event recorded, BR
  moved to `issues/closed/`.

## Required Reads

- `issues/issue_20260721_r17_minimum_operational_toolset_conformance.md` (BR + recon)
- `opencode/specs/mcp-integration-standard/standard.md` R17 (lines 1090-1190)
- `plans/patentmcp_r17-minimum-operational-toolset/design.md` (DD-1..DD-5)
- `src/patent_mcp_server/patents.py` (patentmcp_init :4511, cache_export :5192)
- `src/patent_mcp_server/_token_store.py` (blob_path / list_files / _safe_target)
- `src/patent_mcp_server/_http_app.py` (existing /files blob face — coexists)

## Stop Gates In Force

- No silent fallback anywhere (天条 §11) — every new error is a typed fail-loud surface.
- Widening `patentmcp_init` return type is a public-surface change; keep doctrine
  byte-identical (R15.5) — verified by test, not assumed.
- Do NOT remove the `/files/blob` or `/dav` host extensions.

## Execution-Ready Checklist

- [x] Three gaps confirmed against v0.5.0 source (recon坐实)
- [x] SDK resource API probed (FastMCP.add_resource / read_resource / ResourceTemplate present)
- [x] IDEF0 + GRAFCET validated OK
- [x] design DD-1..DD-5 recorded
