# Errors

## Purpose
- Catalogue expected planning and future execution errors for the prompt-first PatentDrafter architecture.
- This file defines observable error classes; it does not claim all classes are already enforced by runtime code.

## Error Catalogue

| Code | Layer | Message | Cause | Recovery |
|---|---|---|---|---|
| PD-SPEC-001 | plan-builder | Spec skeleton is incomplete | Required lifecycle or companion artifact missing | Add the missing artifact and record the repair in the event log |
| PD-ARCH-001 | architecture | Current-state and target-state architecture are mixed | Historical docs describe future Streamlit/FastAPI/Celery runtime not present in repo | Treat `specs/architecture.md` as SSOT and mark target-state docs as references |
| PD-DATA-001 | file pipeline | Expected handoff artifact is absent | A stage contract references a file not produced by prior stage | Validate the producing agent contract and sample artifact path before implementation |
| PD-AGENT-001 | prompt contract | Agent name or output contract mismatch | `.claude/agents/*.md`, docs, and sample outputs diverge | Normalize naming in specs first; do not silently assume aliases are equivalent |
| PD-TOOL-001 | tooling | Mermaid validation cannot run | `bin/check_mermaid.sh` dependencies or diagram paths unavailable | Verify tool availability and diagram paths; record skipped validation explicitly |
| PD-EXT-001 | external dependency | Patent/search API dependency unavailable | MCP credentials or external service unavailable | Stop for credential/environment resolution; do not fabricate search evidence |

## Recovery Policy
- Fail fast when a required artifact or external evidence source is unavailable.
- Do not add silent fallback behavior for missing APIs, prompts, or files.
- Record unresolved gaps in `docs/events/` before declaring completion.
