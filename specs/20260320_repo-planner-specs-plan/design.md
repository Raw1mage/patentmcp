# Design

## Context
- PatentDrafter repo 目前是以 prompt assets、設計文檔與 sample artifacts 為主的知識型專案。
- `docs/spec/PatentDrafter_Spec.md` 與 `docs/A0_system_idef0.md` 描述了較完整的產品化願景，但 repo 中缺少對應的完整源碼樹與 runtime implementation。
- 因此本次 planning 必須先把「可觀察現況」沉澱到 `specs/`，避免後續 agent 重複用過時文件建模。

## Goals / Non-Goals

**Goals:**
- 建立 repo 現況導向的全域 architecture 文件。
- 讓本次 planner package 成為後續 build/debug 的可執行合約。
- 明確分離 prompt pipeline、sample artifacts、design docs、helper scripts、modeling experiments。

**Non-Goals:**
- 不定義最終產品化架構的唯一答案。
- 不在本次計畫中重構或實作 runtime。

## Decisions
- Decision 1: 以 `source/CLAUDE.md` + `.claude/agents/*.md` + `sample/**` 作為現況 pipeline 的最高可信證據來源。
- Decision 2: 將 `docs/spec/**` 與 `docs/A0_system_idef0.md` 視為重要參考，但標記其偏向目標產品/願景層，而非完全等價於現況實作。
- Decision 3: 新建 `specs/architecture.md`，使未來開發任務優先從 `specs/` 而非散落的 `docs/` 重建心智模型。
- Decision 4: 規劃文件的後續 execution slice 先聚焦「inventory → choose target → implement」，不預設直接落地任何特定 runtime。

## Data / State / Control Flow
- Control Flow: `source/CLAUDE.md` 定義主 Agent 順序控制 → `.claude/agents/*.md` 定義子任務契約。
- Data Flow: 以檔案為中心，從 `raw_document.docx` 逐步流向 `parsed_info.json`、`similar_patents.json`、`patent_outline.md`、內容 markdown、Mermaid 圖表、最終 `complete_patent.md`。
- State Evidence: `sample/**` 是最可見的 pipeline 狀態快照；`docs/**` 與 `hls/**` 提供建模與願景補充。

## Risks / Trade-offs
- 過度依賴歷史 docs -> 可能把未實作的產品構想誤判為現況 -> 以 sample + agent prompts 校正。
- 只做靜態盤點不做 runtime 驗證 -> 可能保留少量未知落差 -> 在 tasks 與 handoff 中保留後續 verification slice。
- 新增 `specs/architecture.md` 會與既有 `docs/` 並存 -> 增加維護責任 -> 以 `specs/architecture.md` 指定為後續 SSOT 降低分歧。

## Critical Files
- `/home/pkcs12/projects/PatentDrafter/specs/architecture.md`
- `/home/pkcs12/projects/PatentDrafter/source/CLAUDE.md`
- `/home/pkcs12/projects/PatentDrafter/source/PATENT_SKILL.md`
- `/home/pkcs12/projects/PatentDrafter/.claude/agents/`
- `/home/pkcs12/projects/PatentDrafter/docs/A0_system_idef0.md`
- `/home/pkcs12/projects/PatentDrafter/docs/spec/PatentDrafter_Spec.md`
- `/home/pkcs12/projects/PatentDrafter/sample/`

## Supporting Docs (Optional)
- `/home/pkcs12/projects/PatentDrafter/docs/events/event_20260320_repo-architecture-planning.md`
