# Handoff

## Execution Contract
- Build agent must read `implementation-spec.md` first.
- Build agent must read `proposal.md`, `spec.md`, `design.md`, `tasks.md`, and `specs/architecture.md` before coding.
- Build agent must materialize runtime todo from `tasks.md` before execution continues.
- Build agent must treat this plan as an inventory-first plan: do not assume Web/API/runtime code already exists just because older docs describe it.

## Required Reads
- `specs/architecture.md`
- `specs/20260320_repo-planner-specs-plan/implementation-spec.md`
- `specs/20260320_repo-planner-specs-plan/proposal.md`
- `specs/20260320_repo-planner-specs-plan/spec.md`
- `specs/20260320_repo-planner-specs-plan/design.md`
- `specs/20260320_repo-planner-specs-plan/tasks.md`
- `docs/events/event_20260320_repo-architecture-planning.md`

## Current State
- Repo architecture inventory has been normalized into `specs/architecture.md`.
- Active plan root has been converted from template to repo-specific planner artifacts.
- No follow-up implementation slice has been selected yet.

## Stop Gates In Force
- Pause if the user has not chosen the next build target.
- Pause if proposed implementation depends on code or runtime components that are only documented aspirationally and not present in repo.
- Return to plan mode if the chosen follow-up work materially changes architecture boundaries beyond this inventory plan.

## Build Entry Recommendation
- Start by asking the user to choose one follow-up direction from this inventory: prompt pipeline hardening, product runtime realization, documentation consolidation, or validation/tooling.

## Execution-Ready Checklist
- [ ] Implementation spec is complete
- [ ] Companion artifacts are aligned
- [ ] Validation plan is explicit
- [ ] Runtime todo seed is present in `tasks.md`
