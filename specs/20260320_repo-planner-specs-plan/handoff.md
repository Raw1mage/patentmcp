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
- Specbase documents describe PatentWorks as `patentmcp` MCP server + `patentworks` skill.
- The analysis flow has been fully implemented under `skills/patentworks/flows/analysis.md` with four distinct scenarios.
- Skill behaviors in `SKILL.md`, `screening.md`, and `drafting.md` have been updated to route to and consume analysis outputs.

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
- [x] Analysis skill implemented
- [x] Skill routing updated
- [x] Screening/drafting handoff updated
