# Observability

## Current Observability Surface
- The current repo has no implemented application telemetry pipeline.
- Observable evidence comes from static prompt contracts, sample artifacts, scripts, and docs.

## Checkpoints

| Checkpoint | Boundary | Signal | Evidence Source |
|---|---|---|---|
| OBS-1 | Main orchestration prompt | Ordered 8-stage pipeline exists | `source/CLAUDE.md` |
| OBS-2 | Agent prompt contracts | Each subagent has input/output responsibility | `.claude/agents/*.md` |
| OBS-3 | File-based data flow | Sample artifacts match stage handoffs | `sample/01_input` through `sample/06_final` |
| OBS-4 | Target-state docs | Docs explicitly mark future-state product design | `docs/spec/PatentDrafter_Spec.md` |
| OBS-5 | Diagram/tool support | Mermaid validation helper exists | `bin/check_mermaid.sh` |
| OBS-6 | Architecture SSOT | Current-state boundary map exists | `specs/architecture.md` |

## Future Runtime Metrics
- Stage duration by agent.
- Handoff artifact validation status.
- External patent/search API success and failure counts.
- Mermaid syntax validation results.
- Final document completeness checks: required sections, terminology consistency, description length.

## Logging Requirements for Future Implementation
- Log every stage transition with session id, stage id, input paths, output paths, and validation status.
- Log external dependency failures without recording secrets.
- Preserve per-stage error evidence under a session-scoped `metadata/agent_logs/` directory if runtime implementation is added.
