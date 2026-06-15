# Tasks

## 1. Inventory Existing Architecture Assets

- [ ] 1.1 Read `specs/architecture.md` and confirm the current repo boundary map
- [ ] 1.2 Review `source/CLAUDE.md` and `.claude/agents/*.md` before touching any execution design
- [ ] 1.3 Compare `docs/**` narratives against `sample/**` artifacts and record any current-state vs target-state mismatch

## 2. Choose the First Build Slice

- [ ] 2.1 Ask the user which follow-up slice should be built from this inventory plan
- [ ] 2.2 Convert the chosen slice into an updated execution phase inside this same plan root
- [ ] 2.3 Identify critical files and validation targets for that chosen slice

## 3. Validate the Existing Pipeline Assumptions

- [ ] 3.1 Verify that the file-based pipeline described in prompts matches sample artifact handoff points
- [ ] 3.2 Validate helper scripts and supporting assets relevant to the chosen slice
- [ ] 3.3 Record evidence and unresolved gaps in the event log

## 4. Execute the Chosen Follow-up Work

- [ ] 4.1 Materialize runtime todo from these tasks before coding
- [ ] 4.2 Implement or refactor only the approved slice
- [ ] 4.3 Sync `specs/architecture.md` if module boundaries or data flow change

## 5. Validate and Close the Loop

- [ ] 5.1 Run targeted validation for the approved slice
- [ ] 5.2 Update `docs/events/` with decisions, evidence, and remaining gaps
- [ ] 5.3 Compare delivered results against `proposal.md` effective requirements before declaring completion
