# Invariants

## Cross-Cutting Guarantees

1. **Architecture SSOT Invariant**
   - `specs/architecture.md` is the first source for repo current-state architecture.
   - Historical docs may inform target-state planning but must not override observable repo evidence.

2. **Prompt-First Current-State Invariant**
   - Until real application code is added, PatentDrafter must be described as a prompt-first / agent-definition-first asset repo.
   - Streamlit, FastAPI, Celery, Redis, and PostgreSQL references remain target-state proposals unless corresponding implementation files exist.

3. **Sequential Handoff Invariant**
   - The patent drafting pipeline flows through input parsing, patent search, outline generation, abstract writing, claims writing, description writing, diagram generation, and markdown merging.

4. **File Contract Invariant**
   - Agent handoff occurs through JSON, Markdown, Mermaid, DOCX, and directory artifacts, not through imported application modules in the current repo state.

5. **No Fabricated Evidence Invariant**
   - Missing search results, credentials, sample outputs, or runtime code must be recorded as gaps; they must not be replaced by invented validation evidence.

6. **Spec Synchronization Invariant**
   - Any future task that adds runtime code, changes module boundaries, or changes data flow must update `specs/architecture.md` and this plan package or create a successor spec.
