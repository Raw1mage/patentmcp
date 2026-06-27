# Event: Analysis RAGBase Distillation
 
## 需求
- 使用者要求：「把這份計畫（0320 計畫）用 specbase 蒸餾成 patentmcp 的 ragbase 吧」。
- 將 0320 計畫中定義的 `analysis` 輸入/輸出契約與核心分析維度，整理成一套可供後續 AI 檢索與起草時作為 Grounding/RAG 參考的文件。

## 範圍

### IN
- 建立本 Event 檔以追蹤進度。
- 建立全新的專利分析知識庫參考文檔 `skills/patentworks/reference/analysis/specification.md`。
- 完整包含分析輸入/輸出 Envelope、7 大核心分析維度、以及與 `docxmcp` 配合的原則。

### OUT
- 不實際撰寫 `flows/analysis.md` 流程。
- 不變更任何 `patentmcp` MCP 伺服器的 Python 程式碼。

## 任務清單
- [x] 1. 建立並補齊 `skills/patentworks/reference/analysis/specification.md`。
- [x] 2. 進行 Debug Checkpoints 驗證。
- [x] 3. 宣告任務完成。

## Debug Checkpoints

### Baseline
- 存在 `specs/20260320_repo-planner-specs-plan` 計畫。
- 目錄 `skills/patentworks/reference/analysis/` 目前不存在。

### Execution
- 建立 `skills/patentworks/reference/analysis/specification.md`，成功將 0320 計畫中有關 `AnalysisInput` / `AnalysisOutput` 資料契約與 7 大核心分析維度進行 RAG 蒸餾。

### Validation
- **驗證項目 1**：確認 [specification.md](file:///home/pkcs12/projects/patentmcp/skills/patentworks/reference/analysis/specification.md) 檔案正確建立。
- **驗證項目 2**：檔案內容已精準包含 Input/Output Envelope 定義、7 大分析產出項目，以及與 `docxmcp` 與 `patentmcp` 物理拆解與語意分析之去重、分段深讀、Handle 管理的協作原則。
- **驗證項目 3**：架構完整性符合 planned 狀態，可直接作為後續 AI 執行 Analysis 任務時的 RAG 規約依據。
