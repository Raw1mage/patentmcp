# Proposal

## Why
- 本 repo 已有大量設計文件、prompt assets 與 sample 產物，但缺少一份位於 `specs/` 體系、可供後續 AI 直接執行的架構盤點契約。
- 現有 `docs/spec/*` 偏目標產品敘事，若不先盤點真實 repo 現況，後續實作容易誤把設計願景當成既有程式基礎。

## Original Requirement Wording (Baseline)
- "盤點本repo架構，用planner建立/specs/plan文件"

## Requirement Revision History
- 2026-03-20: 進入 plan mode，使用既定 plan root `specs/20260320_repo-planner-specs-plan/`。
- 2026-03-20: 盤點後確認 `specs/architecture.md` 缺失，需一併補建，避免 plan 與 repo SSOT 脫節。

## Effective Requirement Description
1. 盤點 PatentDrafter repo 的真實結構與核心資產。
2. 用 planner 產出 execution-ready 的 `/specs/` 文件集。
3. 補齊長期架構 SSOT，明確標示現況與目標態差異。

## Scope

### IN
- 架構盤點。
- planner artifacts 建立與同步。
- architecture/event/modeling 文件補齊。

### OUT
- 實際功能開發。
- 大規模重寫舊 docs。
- 修改 prompt agent 行為。

## Non-Goals
- 不把 repo 直接轉換成可執行的 Web/CLI 應用。
- 不在本次任務中決定最終產品化技術選型。

## Constraints
- 必須以 repo 可觀察事實為準，不能依賴過時文檔假設。
- 必須保留 planner-first 交付格式，讓後續 build agent 可直接接手。
- 必須建立 `docs/events/` 與 `specs/architecture.md`，符合本環境開發流程要求。

## What Changes
- 新增 `specs/architecture.md` 作為 repo 架構單一真相來源。
- 將 `specs/20260320_repo-planner-specs-plan/` 從模板改為實際可用的規劃契約。
- 建立對應 event log，記錄盤點證據與架構同步結果。

## Capabilities

### New Capabilities
- Repo architecture inventory in specs form: 後續 agent 可先讀 `specs/architecture.md` 與本 plan 再行動。
- Planner-ready handoff: 後續 build agent 可直接從 `tasks.md` 和 `handoff.md` 材料化 runtime todo。

### Modified Capabilities
- Repo knowledge grounding: 原本散落於 `docs/`、`source/`、`sample/` 的知識，改由 `specs/` 重新整編為執行契約。

## Impact
- 影響後續所有開發 / 規劃工作流的上下文入口。
- 提升後續 agent 對 repo 現況判斷的準確性。
- 為後續選擇 build slice（例如 UI、workflow、prompt pipeline）提供基準盤點。 
