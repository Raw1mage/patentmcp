# Architecture

## System Overview
- Repo 名稱：PatentDrafter。
- 當前 repo 的可觀察核心是 **prompt-first / agent-definition-first** 的專利起草資產庫，而不是完整的程式化應用實作。
- 主要資產類型包含：主控 prompt、子 agent prompt、專利寫作知識庫、IDEF0/Grafcet 設計文檔、sample 輸出產物、少量輔助腳本與 HLS 建模實驗檔。
- `specs/architecture.md` 是後續規劃與實作的 current-state architecture SSOT；任何未來 runtime / UI / API 實作必須先與本檔同步。

## Top-Level Directory Map
- `source/`
  - 核心 prompt 資產。
  - `CLAUDE.md`：主 Agent 的專案管理與 8 階段流水線指令。
  - `PATENT_SKILL.md`：專利起草知識與法規寫作規範。
  - `Dockerfile`：來源層級的容器化痕跡，但未見完整應用程式碼與 compose/runtime 配套。
- `.claude/agents/`
  - 8 個專業子 agent 定義：`input-parser`、`patent-searcher`、`outline-generator`、`abstract-writer`、`claims-writer`、`description-writer`、`diagram-generator`、`markdown-merger`。
  - 每個 agent 檔案為 prompt contract，描述輸入、輸出、責任與格式。
- `docs/`
  - 長期設計與建模文件。
  - `A0_system_idef0.md`、`A0_system_grafcet.md` 及 `A1`~`A8` IDEF0 文件描述目標系統功能分解。
  - `docs/spec/` 是產品規格視角，偏未來導向目標態。
  - `docs/troubleshooting/` 保存 Mermaid 相關故障排查文檔。
- `sample/`
  - 展示完整專利起草輸出流水線的樣本資料。
  - 目錄結構對應 `01_input`、`02_research`、`03_outline`、`04_content`、`05_diagrams`、`06_final`。
  - 是理解資料流最直接的靜態證據。
- `bin/`
  - `check_mermaid.sh`：Mermaid 驗證腳本。
  - `convert_to_traditional.py`：簡轉繁/文字處理輔助腳本。
- `hls/`
  - HLS / Grafcet 模擬與整合實驗檔，屬建模或原型資產，不是主專利起草主流程的直接 runtime。
- `specs/`
  - `architecture.md`：全域架構 SSOT。
  - `20260320_repo-planner-specs-plan/`：repo 架構盤點與後續執行的 plan-builder package，已包含 lifecycle state 與 planned-state companion artifacts。

## Runtime / Workflow Model
- 主流程為檔案驅動的多 Agent 流水線：
  1. 解析技術交底書
  2. 檢索相似專利
  3. 生成專利大綱
  4. 撰寫摘要
  5. 撰寫權利要求
  6. 撰寫說明書
  7. 生成圖表
  8. 合併最終文件
- 真實可觀察的系統邊界：
  - **控制層**：`source/CLAUDE.md`
  - **工作節點定義**：`.claude/agents/*.md`
  - **知識/規範層**：`source/PATENT_SKILL.md`、`docs/spec/*.md`
  - **資料流樣本**：`sample/**`
- 多數階段透過 JSON / Markdown / Mermaid 檔案銜接，而非函式呼叫或模組 import。

## Canonical Data Flow
- 原始輸入：`raw_document.docx`
- 解析產物：`parsed_info.json`、`raw_document.md`
- 檢索產物：`similar_patents.json`、`prior_art_analysis.md`、`writing_style_guide.md`
- 大綱產物：`patent_outline.md`、`structure_mapping.json`
- 內容產物：`abstract.md`、`claims.md`、`description.md`
- 圖表產物：`05_diagrams/**/*.mmd`
- 最終產物：`complete_patent.md`、`summary_report.md`

## Module Boundaries
- Prompt contract 與 sample artifact 是目前最可信的執行邊界；舊 docs 中提到的 Streamlit / FastAPI / Celery / Redis 屬於設計構想或目標態，不能直接視為已存在實作。
- `source/` 負責 orchestration policy 與寫作知識；`.claude/agents/` 負責 task-specific prompt contract；`sample/` 負責示例資料與結果；`docs/` 負責架構與產品敘事。
- `hls/` 與 `bin/` 不應被誤認為主 pipeline 的核心模組。

## Critical File Index
- `/home/pkcs12/projects/PatentDrafter/source/CLAUDE.md`
- `/home/pkcs12/projects/PatentDrafter/source/PATENT_SKILL.md`
- `/home/pkcs12/projects/PatentDrafter/.claude/agents/input-parser.md`
- `/home/pkcs12/projects/PatentDrafter/.claude/agents/patent-searcher.md`
- `/home/pkcs12/projects/PatentDrafter/.claude/agents/outline-generator.md`
- `/home/pkcs12/projects/PatentDrafter/.claude/agents/markdown-merger.md`
- `/home/pkcs12/projects/PatentDrafter/docs/A0_system_idef0.md`
- `/home/pkcs12/projects/PatentDrafter/docs/A0_system_grafcet.md`
- `/home/pkcs12/projects/PatentDrafter/docs/spec/PatentDrafter_Spec.md`
- `/home/pkcs12/projects/PatentDrafter/sample/06_final/complete_patent.md`

## Key Architectural Tensions
- **現況 vs 目標態落差**：docs/spec 描述的是較完整產品化願景，但 repo 現況主要是 prompt/system assets。
- **程式架構稀薄**：缺少可直接執行的主應用源碼樹，導致後續實作前必須先定義 implementation target。
- **文檔分散**：長期文件主要在 `docs/`，但 planner/runtime contract 則應沉澱至 `specs/`。

## Debug / Observability Map
- 若後續要驗證流水線真實可執行性，優先觀察：
  - `source/CLAUDE.md` 的階段順序與目錄契約
  - `.claude/agents/*.md` 的輸出格式是否與 `sample/**` 一致
  - `bin/check_mermaid.sh` 對 `sample/05_diagrams/*.mmd` 的驗證結果
- 目前 repo 內缺少程式化 runtime log 管線；可觀測性主要靠 sample 產物與文檔。

## Plan-Builder Spec Skeleton
- Active architecture plan root: `specs/20260320_repo-planner-specs-plan/`.
- Lifecycle state: `planned` via `.state.json`.
- Core artifacts: `proposal.md`、`spec.md`、`design.md`、`tasks.md`、`handoff.md`、`implementation-spec.md`.
- Modeling artifacts: `idef0.json`、`grafcet.json`、`c4.json`、`sequence.json`.
- Code-independence companions: `data-schema.json`、`test-vectors.json`、`errors.md`、`observability.md`、`invariants.md`.
- This package documents repo architecture and readiness gates only; it does not imply that target-state Web/CLI/runtime implementation already exists.

## Architecture Sync Note
- 本檔建立於 2026-03-20，用於把 repo 可觀察現況同步到 `specs/` 體系。
- 2026-05-03: 已重新建立 spec-compliant skeleton，補齊 lifecycle state 與 planned-state companion artifacts；架構現況仍維持 prompt-first / agent-definition-first，未新增 runtime module boundary。
- 後續若新增真正的 Web/CLI runtime 程式碼、工作流控制器或 API 層，必須直接更新本檔對應章節，而非只更新 `docs/`。
