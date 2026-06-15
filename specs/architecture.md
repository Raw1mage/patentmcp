# Architecture

## System Overview
- Repo 名稱：PatentDrafter / PatentWorks。
- 當前 repo 的可觀察核心是 **PatentWorks = patentmcp MCP server + patentworks skill**，而不是舊版八階段 prompt agent 應用。
- 產品目標是把專利工作拆成三個可單獨使用、也可串接的能力層：`檢索`、`分析`、`撰寫`。
- `specs/architecture.md` 是後續規劃與實作的 current-state architecture SSOT；若 skill flow、MCP tool 或資料交付契約改變，必須同步本檔。

## Top-Level Directory Map
- `README.md`
  - 現行產品定位入口：PatentWorks 是 MCP server + skill 組合包。
  - 明確標示 2026-06 後已與舊 AGPL 前身斷開，舊 8 層多 Agent 架構、HLS/Grafcet 實驗等皆已廢除。
- `vendor/patents-mcp/`
  - `patentmcp` MCP server。
  - 提供 Google Patents、TIPO GPSS、USPTO、BigQuery 等專利資料檢索與取文能力。
  - 提供 `build_screening_table` 與 `stage_file`，把候選資料或成品落地成 token/blob handle，避免 bytes 進入模型 context。
- `skills/patentworks/`
  - 現行專利工作 skill。
  - `SKILL.md` 是 flow router；`flows/` 定義 disclosure、screening、drafting；`reference/` 保存交底書與法域撰寫知識。
- `skills/patent-practitioner-workflow.md`
  - 領域流程骨幹，記錄人類專利檢索、判讀、分析與報告產出方式。
  - 是設計檢索/分析 skill 邊界的重要依據。
- `refs/`
  - 外部專利專案參考材料。
  - 授權紅線：MIT 內容可借鑑；AGPL 來源僅供研讀，不得把程式碼複製進本產品。
- `output/`
  - 本地產出樣本，例如檢索 spreadsheet。
- `specs/`
  - `architecture.md`：全域架構 SSOT。
  - `20260320_repo-planner-specs-plan/`：現行 specbase/plan-builder package，需從舊 repo skeleton 重構為 PatentWorks 現況與後續分析技能切分契約。
- `.mcp.json`
  - 本地 MCP server 註冊，指向 `vendor/patents-mcp`。
  - 含本地憑證路徑設定；不得假設憑證可提交或可外流。

## Runtime / Workflow Model
- 現行主流程是 skill 編排 MCP/tool 產物的工作站：
  1. `disclosure`：使用者材料、idea、文件或專案內容 → 結構化技術交底書。
  2. `screening`：技術問題 + CPC/keyword → 專利候選召回、建表、逐列判讀、評分 spreadsheet。
  3. `analysis`：資料來源無關的理解/比對層，應可消化檢索 MCP 產物或使用者直接提供內容。
  4. `drafting`：以分析後的結構化結果與目標法域知識 → 請求項、說明書、摘要。
- `analysis` 是要獨立化的中介能力：不應假設資料一定來自 `screening` 或 `patentmcp`。
- `screening` 仍可內含「逐列消化/預篩」作為檢索交付物 enrich 步驟，但可重用的技術特徵抽取、要件對照、差異點歸納、最接近前案判斷，應沉澱為獨立 analysis contract。

## Canonical Data Flow
- 使用者材料路徑：user content / files / disclosure → `analysis` → `drafting`。
- 檢索材料路徑：`patentmcp` search/get/build table → screening spreadsheet / handles → `analysis` → novelty/feature matrix/drafting basis → `drafting`。
- 混合材料路徑：使用者交底 + MCP 前案 + shortlist full claims → `analysis` → claim boundary / technical difference / report → `drafting`。
- 成品交付契約：大型表格、PDF、圖、全文與 docx 類產物走 token/blob handle；模型回覆只提供白話摘要、決策點、handle 與必要引用。

## Module Boundaries
- **檢索層 (`patentmcp`, `screening`)**
  - 負責資料取得、CPC/keyword 查詢、候選去重、建表、取文、PDF/figure/fulltext handle 化。
  - 不負責最終法律裁決；只提供可稽核資料與 AI 預篩欄位。
- **分析層 (`analysis`, planned skill boundary)**
  - 負責把任意來源材料正規化為技術特徵、要件對照、差異點、風險/新穎性綜述、drafting basis。
  - 輸入來源可為 `retrieval_mcp`、`user_provided`、`file`、`mixed`。
  - 輸出應是結構化、可被 drafting 使用的中間產物，而非直接綁定 CSV 或 MCP schema。
  - CSV 大檔的讀取、切批、抽樣、索引與分工策略由執行 agent 自主決定；架構只要求結果可稽核、來源可追溯、不可捏造證據。
- **撰寫層 (`drafting`)**
  - 負責依目標法域載入 `reference/drafting/common.md` 與 TW/CN/US/EP 法域知識。
  - 吃 analysis 產出的必要技術特徵、最接近前案、區別技術特徵、實施例與術語表。
- **文件/交付層 (`stage_file`, docxmcp-style handle)**
  - 負責把大型或二進位交付物落地並回 token/blob handle。

## Critical File Index
- `/home/pkcs12/projects/PatentDrafter/README.md`
- `/home/pkcs12/projects/PatentDrafter/.mcp.json`
- `/home/pkcs12/projects/PatentDrafter/vendor/patents-mcp/src/patent_mcp_server/patents.py`
- `/home/pkcs12/projects/PatentDrafter/skills/patentworks/SKILL.md`
- `/home/pkcs12/projects/PatentDrafter/skills/patentworks/flows/disclosure.md`
- `/home/pkcs12/projects/PatentDrafter/skills/patentworks/flows/screening.md`
- `/home/pkcs12/projects/PatentDrafter/skills/patentworks/flows/drafting.md`
- `/home/pkcs12/projects/PatentDrafter/skills/patent-practitioner-workflow.md`
- `/home/pkcs12/projects/PatentDrafter/specs/20260320_repo-planner-specs-plan/`

## Key Architectural Tensions
- **舊 spec vs 現行 README 落差**：舊 `specs/architecture.md` 仍描述 `source/`、`.claude/agents/`、`sample/` 八階段 prompt pipeline，但現行 repo 已重定位為 PatentWorks MCP + skill。
- **分析能力耦合過深**：目前 `screening.md` 內同時描述召回、建表、逐列判讀與可專利性綜述；應切出資料來源無關的 analysis 層，讓使用者提供內容也能直接進分析。
- **交付物 vs 中間產物混用**：screening 的最終交付是 scored CSV，但 drafting 需要的是結構化分析基礎；兩者不應互相假設格式。
- **法遵邊界**：AI 做預篩、分析與起草草稿；人類仍需複核法律裁決。

## Debug / Observability Map
- 檢索工具邊界：`vendor/patents-mcp/src/patent_mcp_server/patents.py` 的 MCP tool docstring 與返回 schema。
- Skill routing：`skills/patentworks/SKILL.md` 的 flow 選擇表。
- 檢索/分析領域規格：`skills/patent-practitioner-workflow.md`。
- Flow 契約：`skills/patentworks/flows/*.md`。
- MCP 啟動設定：`.mcp.json`。
- 成品樣本：`output/**/*.csv`。

## Plan-Builder Spec Package
- Active plan root: `specs/20260320_repo-planner-specs-plan/`。
- Core artifacts: `proposal.md`、`spec.md`、`design.md`、`tasks.md`、`handoff.md`、`implementation-spec.md`。
- 本 package 現在的任務是把 specbase 文件重構為現行 PatentWorks 架構，並為「獨立 analysis skill」建立可執行契約。
- 本 package 不代表已完成 analysis skill 實作；它定義下一步實作與驗證邊界。

## Architecture Sync Note
- 2026-06-15: 已將架構 SSOT 從舊八階段 prompt pipeline 重構為 PatentWorks MCP + skill 現況；新增 analysis 作為資料來源無關的 planned boundary。
- 後續若新增 `flows/analysis.md`、調整 `SKILL.md` flow router、或修改 MCP table schema，必須同步本檔與 plan package。
