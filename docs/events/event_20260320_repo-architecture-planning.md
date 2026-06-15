# Event: Repo Architecture Planning

## 需求
- 使用者要求：盤點本 repo 架構，用 planner 建立 `/specs/plan` 文件。

## 範圍

### IN
- 盤點目前 repo 的真實目錄、核心 prompt/agent 資產、sample 產物與建模文件。
- 建立本次 plan root：`specs/20260320_repo-planner-specs-plan/`。
- 補齊缺失的 `specs/architecture.md`，作為後續開發/規劃的 codebase SSOT。
- 產出對應的 IDEF0 / Grafcet / C4 / Sequence 規劃模型。

### OUT
- 不修改 repo 的功能行為。
- 不重寫既有 docs 內容，只在規劃文件中記錄現況與落差。
- 不進入 build/implementation 階段。

## 任務清單
- 盤點既有 docs/specs/.claude/source/sample/hls/bin 資產。
- 釐清 repo 真實架構與歷史文件宣稱的差異。
- 建立 architecture/event/plan artifacts。
- 建立 execution-ready 的 planner handoff。

## 對話重點摘要
- 使用者要的是「架構盤點 + 用 planner 建 plan」，不是直接做功能實作。
- 已切換到 plan mode，使用既定 plan root：`specs/20260320_repo-planner-specs-plan/`。

## Debug Checkpoints

### Baseline
- `specs/20260320_repo-planner-specs-plan/` 已自動建立，但內容仍為模板。
- `specs/architecture.md` 不存在。
- `docs/events/` 原本不存在。
- `docs/` 與 `docs/spec/` 對系統描述偏產品/目標態，與 repo 實際檔案結構有落差。

### Instrumentation Plan
- 讀取既有 plan 模板檔，確認需替換的 section。
- 讀取 `source/CLAUDE.md`、`source/PATENT_SKILL.md`、`.claude/agents/*.md` 代表檔，確認主/子 agent 實際流程。
- 讀取 `docs/README.md`、`docs/spec/PatentDrafter_Spec.md`、`docs/A0_system_idef0.md`、`docs/A0_system_grafcet.md`，辨識現有長期設計敘述。
- 掃描 `sample/`、`bin/`、`hls/`，確認 repo 內尚有示例產物與建模實驗檔。

### Execution
- 已確認 repo 真實核心為 prompt-first 資產庫：`source/` + `.claude/agents/` + `docs/` + `sample/`。
- 已確認 sample 目錄完整反映 01_input → 06_final 的產物管線。
- 已確認 `bin/check_mermaid.sh` 與 `bin/convert_to_traditional.py` 為少數輔助腳本。
- 已確認 `hls/` 為獨立建模/模擬資產，非主流程 runtime。

### Root Cause
- 歷史文件描述了一個更完整的目標產品（含 Streamlit/FastAPI/Celery 等），但 repo 當前可直接觀察到的主要資產仍以 prompt、agent 指令、設計文件與 sample artifacts 為主。
- 因此若不先建立 `specs/architecture.md` 與新的 planner package，後續 agent 很容易把「目標態」誤認為「現況」。

### Validation
- 已建立 `docs/events/`。
- 已建立本 event 檔。
- 已建立 `specs/architecture.md`，並以 repo 可觀察現況完成架構同步。
- 已將 `specs/20260320_repo-planner-specs-plan/` 全部 companion artifacts 從模板替換為 repo-specific 內容。
- Architecture Sync: Verified (Doc changes applied to `specs/architecture.md` based on `source/`、`.claude/agents/`、`docs/`、`sample/`、`bin/`、`hls/` evidence).
