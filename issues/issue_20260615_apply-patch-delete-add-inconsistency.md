# Bug Report: apply_patch delete/add inconsistency during specbase rewrite

## Summary
- During specbase refactor, `tasks.md` was intended to be replaced with a new task list.
- The patch operation was reported as successful, but the resulting filesystem state left `specs/20260320_repo-planner-specs-plan/tasks.md` deleted.
- I incorrectly described this as "patch 被還原"; the more accurate RCA is an inconsistent/failed replacement workflow plus my bad follow-up handling.

## Impact
- `specs/20260320_repo-planner-specs-plan/tasks.md` is currently deleted in the working tree.
- Other spec files were modified as intended.
- An unrelated pre-existing modification exists at `vendor/patents-mcp/src/patent_mcp_server/gpatents/client.py`; it was not touched by this spec refactor and should not be mixed into this RCA.

## Evidence
- `git status --short` showed `D specs/20260320_repo-planner-specs-plan/tasks.md` after the patch sequence.
- `git diff -- specs/20260320_repo-planner-specs-plan/tasks.md specs/20260320_repo-planner-specs-plan/handoff.md` showed `tasks.md` deleted and `handoff.md` updated.
- A later `glob` for `specs/20260320_repo-planner-specs-plan/tasks.md` returned no file.

## Timeline
- I applied a combined patch that deleted and re-added multiple spec files, including `tasks.md` and `handoff.md`.
- The tool returned success, but `tasks.md` did not remain present.
- I then tried to re-add `tasks.md`, but one attempt had malformed JSON input and did not execute.
- I used the phrase "patch 被還原", which was inaccurate because there is no evidence of an external revert.

## Root Cause
- Primary: unsafe combined delete/add replacement for multiple files made it harder to verify each file outcome immediately.
- Secondary: I trusted the success message too broadly and did not immediately verify `git status` before continuing.
- Tertiary: my follow-up re-add attempt was malformed, leaving the deletion unresolved.

## Corrective Action
- Restore `tasks.md` in a separate, single-file operation.
- Re-run `git status --short` and targeted reads after restoring.
- Avoid wording like "被還原" unless there is evidence of an external process or user action reverting files.
- Prefer smaller per-file patches for spec package rewrites.

## Current Status
- Open.
- Stop gate: wait for user confirmation before restoring `tasks.md` and continuing spec refactor.
