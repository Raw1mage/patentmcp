# Event: Repo Spec Skeleton Rebuild

## 需求
- 使用者要求：「啟用plan-builder，針對本repo的架構進行分析，重新建立spec合規的骨架文件」。

## 範圍(IN)
- 使用 plan-builder lifecycle 重新檢查既有 `specs/20260320_repo-planner-specs-plan/`。
- 針對 repo 架構現況補齊 planned-state spec skeleton。
- 建立 `.state.json`、data contract、test vectors、errors、observability、invariants 等缺失文件。
- 同步 `specs/architecture.md` 與 event log 的驗證證據。

## 範圍(OUT)
- 不修改 patent drafting prompt 行為。
- 不新增 Web/CLI runtime。
- 不更動 sample patent outputs。
- 不提交 git commit。

## 任務清單
- 1. 盤點現有 specs/docs 事件與 plan-builder 骨架狀態。
- 2. 分析 repo 架構與主要模組邊界。
- 3. 建立或修補 spec 合規骨架文件。
- 4. 同步架構文件與本次 event log。
- 5. 驗證骨架完整性並回報結果。

## Debug Checkpoints

### Baseline
- 既有 `specs/20260320_repo-planner-specs-plan/` 已包含 proposal/spec/design/tasks/handoff/model JSON，但缺少 `.state.json`。
- 缺少 planned-state companion artifacts：`data-schema.json`、`test-vectors.json`、`errors.md`、`observability.md`、`invariants.md`。
- `specs/architecture.md` 已存在，但需要補充 2026-05-03 skeleton rebuild 後的合規狀態。

### Instrumentation Plan
- 讀取 `specs/architecture.md`、既有 event log、source prompts、代表性 agent prompts、A0 IDEF0/Grafcet、產品 spec。
- 以 `glob` 檢查 missing artifacts。
- 委派 explore agent 做只讀架構盤點，用於交叉確認。

### Execution
- 已確認 repo 現況仍是 prompt-first / agent-definition-first asset repo。
- 已確認 `docs/spec/PatentDrafter_Spec.md` 自身標註為目標規格，而非已實作功能。
- 已新增 plan-builder lifecycle 與 planned-state companion skeleton。

### Root Cause
- 舊骨架是 planner-era 文件集，具備局部規劃內容但沒有新版 plan-builder lifecycle state 與 code-independence companion artifacts。
- 若不補齊 `.state.json` 與 companion artifacts，後續 agent 無法依 spec state 判定 required reads、validation gates 與 drift handling。

### Validation
- Present: `specs/20260320_repo-planner-specs-plan/.state.json` declares lifecycle state `planned`.
- Present: planned-state companion artifacts now exist: `data-schema.json`、`test-vectors.json`、`errors.md`、`observability.md`、`invariants.md`.
- Present: existing core/model artifacts remain in place: proposal/spec/design/tasks/handoff/implementation-spec plus IDEF0/Grafcet/C4/Sequence JSON.
- Explore result: independent read-only inspection confirmed root assets are `source/`、`.claude/agents/`、`sample/`、`docs/`、`bin/`、`hls/` and confirmed no root-level Streamlit/FastAPI runtime files are present.
- Architecture Sync: Updated `specs/architecture.md` to record the spec-compliant skeleton, lifecycle state, and companion artifacts. No runtime module boundary changes were introduced.

## Remaining
- This task rebuilt the architecture/spec skeleton only. Any future implementation must first select a build slice and update `tasks.md` / `handoff.md` accordingly.
