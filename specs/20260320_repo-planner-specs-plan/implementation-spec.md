# Implementation Spec

## Goal
- 重構 PatentDrafter specbase 文件，使其反映現行 PatentWorks 架構，並為後續獨立 `analysis` skill flow 建立可執行契約。

## Scope

### IN
- 更新 repo 架構 SSOT 為 PatentWorks MCP + skill。
- 將 plan package 重寫為 analysis boundary refactor spec。
- 定義 `檢索 → 分析 → 撰寫` 的責任切分與 handoff。
- 定義 analysis input/output envelope 與後續 implementation tasks。

### OUT
- 不直接新增 `skills/patentworks/flows/analysis.md`。
- 不直接修改 `skills/patentworks/SKILL.md` routing。
- 不直接修改 `screening.md` 或 `drafting.md` 行為。
- 不執行 MCP 檢索測試。

## Assumptions
- `README.md` 是目前產品定位的最高層入口。
- `vendor/patents-mcp/src/patent_mcp_server/patents.py` 是 MCP tool 邊界的可觀察實作。
- `skills/patentworks/flows/*.md` 是 skill 行為契約來源。
- 使用者目前要的是 specbase 重構，不是立即 coding。

## Stop Gates
- 若要進入 implementation，需先確認是否新增 `flows/analysis.md`，或只重構既有 `screening.md`/`drafting.md` handoff。
- 若 analysis output schema 要落成機器可驗證 JSON，需另行決定 schema 檔位置與相容策略。
- 若要讀寫 CSV 實體內容，需確認可用的 CSV 讀寫策略與 token/blob 交付路徑。

## Critical Files
- `/home/pkcs12/projects/PatentDrafter/specs/architecture.md`
- `/home/pkcs12/projects/PatentDrafter/specs/20260320_repo-planner-specs-plan/proposal.md`
- `/home/pkcs12/projects/PatentDrafter/specs/20260320_repo-planner-specs-plan/spec.md`
- `/home/pkcs12/projects/PatentDrafter/specs/20260320_repo-planner-specs-plan/design.md`
- `/home/pkcs12/projects/PatentDrafter/specs/20260320_repo-planner-specs-plan/tasks.md`
- `/home/pkcs12/projects/PatentDrafter/specs/20260320_repo-planner-specs-plan/handoff.md`
- `/home/pkcs12/projects/PatentDrafter/skills/patentworks/flows/screening.md`
- `/home/pkcs12/projects/PatentDrafter/skills/patentworks/flows/drafting.md`

## Structured Execution Phases
- Phase 1 — Specbase Architecture Sync: replace obsolete prompt-pipeline architecture with PatentWorks MCP + skill boundaries.
- Phase 2 — Analysis Boundary Definition: define source-agnostic input/output and responsibilities.
- Phase 3 — Handoff Planning: identify how screening and drafting should call or consume analysis.
- Phase 4 — Implementation Preparation: seed tasks for future `flows/analysis.md` and routing updates.
- Phase 5 — Validation: verify all spec artifacts describe the same boundary and no old critical paths remain authoritative.

## Validation
- Confirm `specs/architecture.md` names PatentWorks MCP + skill as current state.
- Confirm `spec.md` requires analysis to accept retrieval MCP and user-provided materials.
- Confirm `design.md` defines input/output envelope.
- Confirm `tasks.md` seeds implementation work without claiming it is already done.
- Confirm `handoff.md` tells future agents where to start.

## Handoff
- Future implementation agent must read this file first.
- Future implementation agent must update `skills/patentworks` only after checking this spec and `specs/architecture.md`.
- First implementation slice should likely be `skills/patentworks/flows/analysis.md` plus `SKILL.md` router update.
- Screening/drafting changes should be minimal and handoff-oriented.
