# Event Log: Patent Technical Insight Report Workflow Upgrades

- **Date**: 2026-06-27
- **Topic**: Patent Technical Insight Report Workflow Upgrades
- **Scope**:
  - **IN**: Update `patentworks` skill files to incorporate detailed query logging, query-level CPC restriction (no secondary CPC filter), 1-5 level relevance rating, dynamic Level 5 analysis, and domain-specific plain-language claims analysis optimized for a parameterized target product or development topic.
  - **OUT**: Modify the python code base for search logic (the logic runs on the LLM side guided by the flow files).

---

## Debug Checkpoints

### Baseline
- `patentworks` flow files currently define relevance as 1-3 stars.
- `priorsearch.md` has memory-based secondary CPC filtering instead of strict query-level AND scoping.
- Detailed analysis shortlist is capped at a fixed N (usually 20).
- Shortlist claim analysis lacks structured plain-language domain insights (long-term care smart homes).

### Instrumentation Plan
- Modify `SKILL.md` to update CSV column definitions.
- Modify `flows/screening.md` to update 1-5 level definitions.
- Modify `flows/priorsearch.md` to incorporate query logging, query-level CPC restrictions, 1-5 level relevance, dynamic Level 5 detailed analysis, and long-term care insight guidance.
- Sync and validate wiki using `spec_sync` and `wiki_validate`.

### Execution
- Successfully updated `SKILL.md` to set candidate relevance rating scale to 1-5 levels.
- Successfully modified `flows/screening.md` to define 1-5 level ratings criteria.
- Successfully patched `flows/priorsearch.md` to:
  1. Mandate structured query logging in §1 of the report.
  2. Enforce query-level CPC/IPC filtering and ban secondary post-search CPC filtering.
  3. Change relevance rating from 1-3 stars to 1-5 levels.
  4. Shortlist and analyze all Level 5 patents dynamically (no fixed limit).
  5. Guide the plain-language claim analysis section with specific questions and parameterized target product/development topic (e.g., long-term care smart home) insights.
- Generalized the "long-term care smart home" context in `priorsearch.md` into a template parameter `[目標產品/開發主題] (例如：長照智慧家庭)` so it is a reusable, generalized workflow playbook.

### Root Cause
- The previous workflow was too coarse (1-3 stars, fixed shortlist size), sometimes led to over-filtering of relevant patents due to secondary CPC filtering, and lacked parameterized, reusable product development insights.

### Validation
- Ran `spec_sync` and `wiki_rebuild_index` to rebuild the index database.
- Ran `wiki_validate` on the entire workspace. Returned 0 broken links, 0 orphans, 0 missing backlinks (ALL PASSED).
