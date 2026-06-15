# Errors

## Purpose
- Catalogue expected planning and future execution errors for the PatentWorks MCP + skill architecture.
- This file defines observable error classes; it does not claim all classes are already enforced by runtime code.

## Error Catalogue

| Code | Layer | Message | Cause | Recovery |
|---|---|---|---|---|
| PD-SPEC-001 | plan-builder | Spec skeleton is incomplete | Required lifecycle or companion artifact missing | Add the missing artifact and record the repair in the event log |
| PD-ARCH-001 | architecture | Current-state and target-state architecture are mixed | Old prompt-pipeline docs are treated as current PatentWorks behavior | Treat `specs/architecture.md` as SSOT and mark historical docs as references |
| PD-MCP-001 | retrieval MCP | Patent source unavailable | MCP credentials, GPSS user code, Google endpoint, or external service unavailable | Stop for credential/environment resolution; do not fabricate search evidence |
| PD-SCREEN-001 | screening | Candidate set is too broad | Search hits exceed the agreed analysis/table limit | Narrow CPC, keyword, date, or database scope before analysis |
| PD-ANALYSIS-001 | analysis | Source type or materials are underspecified | User content, handle, or MCP result lacks enough context for the requested analysis goal | Ask for missing material or downgrade to a clearly scoped partial analysis |
| PD-ANALYSIS-002 | analysis | Analysis output is tied to raw MCP/CSV schema | Drafting handoff depends on retrieval-specific columns instead of normalized features | Normalize into `AnalysisOutput` before drafting |
| PD-DRAFT-001 | drafting | Drafting starts without target jurisdiction or analysis basis | Drafting flow lacks jurisdiction knowledge or structured technical basis | Confirm jurisdiction and use analysis output before claims-first drafting |

## Recovery Policy
- Fail fast when a required artifact or external evidence source is unavailable.
- Do not add silent fallback behavior for missing APIs, handles, schemas, or user materials.
- Record unresolved gaps via specbase event log before declaring completion.
