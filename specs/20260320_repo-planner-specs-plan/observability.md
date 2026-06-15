# Observability

## Current Observability Surface
- The current repo has no implemented application telemetry pipeline.
- Observable evidence comes from `README.md`, `patentmcp` tool definitions, `patentworks` skill flow files, local output artifacts, and specbase documents.

## Checkpoints

| Checkpoint | Boundary | Signal | Evidence Source |
|---|---|---|---|
| OBS-1 | Product positioning | PatentWorks is MCP server + skill package | `README.md` |
| OBS-2 | Retrieval MCP | Search/get/build-table/stage-file tools exist | `vendor/patents-mcp/src/patent_mcp_server/patents.py` |
| OBS-3 | Skill routing | disclosure/screening/drafting flows are routed | `skills/patentworks/SKILL.md` |
| OBS-4 | Flow contracts | screening keeps CSV delivery; drafting keeps jurisdiction knowledge | `skills/patentworks/flows/*.md` |
| OBS-5 | Analysis boundary | Source-agnostic analysis is planned but not implemented | `specs/architecture.md`, `design.md` |
| OBS-6 | Architecture SSOT | Current-state boundary map exists | `specs/architecture.md` |

## Future Runtime Metrics
- MCP tool success/failure counts by source.
- Screening table row counts, deduped counts, source gaps, and too-broad stops.
- Analysis material counts by `sourceType` and analysis goal.
- Handoff artifact validation status.
- External patent/search API success and failure counts.
- Final drafting completeness checks: required sections, terminology consistency, claim/support alignment.

## Logging Requirements for Future Implementation
- Log every flow transition with session id, flow id, material source type, handles, and validation status.
- Log external dependency failures without recording secrets or credential paths.
- Preserve MCP gaps and analysis review flags as first-class evidence; do not replace unavailable sources with silent fallback data.
