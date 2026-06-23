# Invariants

## Cross-Cutting Guarantees

1. **Architecture SSOT Invariant**
   - `specs/architecture.md` is the first source for repo current-state architecture.
   - Historical docs may inform target-state planning but must not override observable repo evidence.

2. **PatentWorks Current-State Invariant**
   - PatentDrafter must be described as PatentWorks: `patentmcp` MCP server plus `patentworks` skill flows.
   - Historical prompt-agent, HLS, or product-runtime narratives remain references unless current files explicitly reintroduce them.

3. **Source-Agnostic Analysis Invariant**
   - Analysis must accept retrieval MCP output, user-provided content, file-derived materials, or mixed inputs.
   - Analysis output must normalize materials into technical features, element maps, differences, drafting basis, and review flags.

4. **Delivery Contract Invariant**
   - Screening final delivery remains a human-readable scored spreadsheet.
   - Large files and binary artifacts move by token/blob handle, not model context bytes.

5. **No Fabricated Evidence Invariant**
   - Missing search results, credentials, handles, user materials, or runtime code must be recorded as gaps; they must not be replaced by invented validation evidence.

6. **Spec Synchronization Invariant**
   - Any future task that adds `flows/analysis.md`, changes skill routing, changes MCP contracts, or changes data flow must update `specs/architecture.md` and this plan package or create a successor spec.
