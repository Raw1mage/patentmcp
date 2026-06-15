# Handoff

## Execution Contract
- Future implementation agent must read `implementation-spec.md` first.
- Future implementation agent must read `specs/architecture.md`, `proposal.md`, `spec.md`, `design.md`, and `tasks.md` before editing skill files.
- Treat this package as the source of truth for the analysis boundary: `analysis` is not a sub-step owned exclusively by `screening`.
- Do not modify MCP tool schemas unless the user explicitly approves a broader implementation slice.

## Required Reads
- `specs/architecture.md`
- `specs/20260320_repo-planner-specs-plan/implementation-spec.md`
- `specs/20260320_repo-planner-specs-plan/proposal.md`
- `specs/20260320_repo-planner-specs-plan/spec.md`
- `specs/20260320_repo-planner-specs-plan/design.md`
- `specs/20260320_repo-planner-specs-plan/tasks.md`
- `skills/patentworks/SKILL.md`
- `skills/patentworks/flows/screening.md`
- `skills/patentworks/flows/drafting.md`
- `skills/patent-practitioner-workflow.md`

## Current State
- Specbase documents now describe PatentWorks as `patentmcp` MCP server + `patentworks` skill.
- Analysis is specified as a planned source-agnostic layer.
- No skill behavior has been changed yet.
- Future implementation should start with `tasks.md` section 3.

## Stop Gates In Force
- Pause before adding `flows/analysis.md` if the user wants only documentation/spec changes.
- Pause before formalizing JSON schema if the user has not approved a machine-readable schema slice.
- Pause before changing MCP server behavior, CSV writer behavior, or token/blob delivery contracts.

## Build Entry Recommendation
- First implementation slice: add `skills/patentworks/flows/analysis.md`, update `SKILL.md` routing, and lightly adjust `screening.md` / `drafting.md` handoff language.
- Keep implementation minimal: no new fallback mechanisms, no MCP schema changes, no CSV logic changes.

## Execution-Ready Checklist
- [x] Architecture SSOT updated
- [x] Proposal/spec/design aligned
- [x] Future tasks seeded
- [ ] Analysis skill implemented
- [ ] Skill routing updated
- [ ] Screening/drafting handoff updated
