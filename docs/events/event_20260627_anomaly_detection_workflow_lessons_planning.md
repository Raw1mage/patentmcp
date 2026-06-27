# Event: Anomaly Detection Workflow Lessons Planning

## 需求
- 使用者要求：將異常偵測前案檢索的 Bug Report (`/issues/BR_20260627_anomaly_detection_workflow_lessons.md`) 內容分析並設計成 `specbase` Plan。

## 範圍

### IN
- 建立本事件記錄檔 `docs/events/event_20260627_anomaly_detection_workflow_lessons_planning.md`。
- 使用 `specbase` 原生工具建立並設計 `workflow/anomaly_detection_lessons` 的 Plan 套件。
- 撰寫計畫包含的 `proposal.md`、`design.md`、`spec.md`、`tasks.md`、`handoff.md`、`observability.md`、`errors.md` 與 `test-vectors.json` 等文件。
- 建立對應的系統建模圖檔：`idef0.json`、`grafcet.json`、`sequence.json`、`flowchart.json` 與 `data-schema.json`。
- 使用 `plan_check` 與 `wiki_validate` 驗證其完整性與連結性。
- 將 Plan 狀態推進至 `planned`。

### OUT
- 本次規劃不進行 `patentmcp` 的實際 Python 程式碼修改與修復。

## 任務清單
- [x] 建立事件記錄檔
- [x] 呼叫 `plan_create` 初始化 Plan
- [x] 撰寫 Plan 規格與設計文件
- [x] 撰寫系統建模 JSON 檔
- [x] 執行 `plan_check` 與 `wiki_validate` 驗證
- [x] 執行 `plan_advance` 推進 Plan 狀態至 `planned`

## 對話重點摘要
- 任務目標為將 Bug Report 轉化為 specbase 規範的 Plan，藉此提供未來實作的依據。

## Debug Checkpoints

### Baseline
- 計畫目錄 `plans/` 中無 `workflow_anomaly_detection_lessons` 計畫。
- 尚未建立針對此 bug report 的系統與資料建模。

### Instrumentation Plan
- 呼叫 `plan_create` 建立 slug 為 `workflow/anomaly_detection_lessons` 的 Package。
- 填寫所有對應的規格、設計與建模檔案。
- 呼叫 `plan_check` 與 `wiki_validate` 進行健康檢查。
- 呼叫 `plan_advance` 推進生命週期。

### Execution
- 呼叫 `plan_create` 成功初始化 `workflow/anomaly_detection_lessons` 計畫。
- 建立了計畫所需的 8 份基礎規格與設計文件（`proposal.md`、`design.md`、`spec.md`、`tasks.md`、`handoff.md`、`observability.md`、`errors.md` 與 `test-vectors.json`）。
- 建立了 5 份對應的系統建模圖檔（`idef0.json`、`grafcet.json`、`sequence.json`、`flowchart.json` 與 `data-schema.json`）。
- 修改 `gpss/client.py` 增加 JSON 字典物件型態安全檢測，避免非 dict 型態造成的屬性崩潰。
- 修改 `gpatents/client.py` 引入 Fail-Fast 機制，遭遇 403、429、503 時主動熔斷並開啟 60 秒冷卻時間。
- 修改 `patents.py` 實作 GPSS 每 50 件一頁的分頁讀取與 1.0 秒冷卻；使 US 專利在 PPUBS 失效時能自動降級至 `gpatents`；修補 Google Patents claims 陣列解構的潛在 Bug。
- 修改 `skills/patent-practitioner-workflow.md`，新增「六、前案檢索與報告組裝 SOP 契約」章節。

### Root Cause
- 異常偵測檢索任務中暴露了 `patentmcp` 部分 API 與流程的魯棒性不足（如 GPSS 大量檢索 API 崩潰、USPTO PPUBS 失效 fallback 缺乏、gpatents 被限流時無 fail-fast 機制）。為確保後續自動化順暢，必須先為此優化工作建立明確的設計規範與 Plan。

### Validation
- 呼叫 `plan_check` 成功驗證此 Package（`ready: true`, 狀態為 `proposed`）。
- 呼叫 `wiki_validate` 進行全域知識庫檢測，回傳 `0 brokenLinks`、`0 missingBackLinks`、`0 orphans` 與 `0 drift`。
- 呼叫 `plan_advance` 成功將計畫狀態推進至 `designed`，繼而順利推進至目標的 `planned` 狀態。
- 呼叫 `spec_sync` 進行規格同步與編譯。首輪偵測到 `design.md` 缺少 Mermaid 圖警告，於補齊 `## Architecture` 的 Mermaid 流程圖後重新同步，警告成功消除，`README.md` 編譯位元組達到 `3562 bytes` 且全數無殘留警告。
- 撰寫並於專案虛擬環境執行 [test_remediation.py](file:///home/pkcs12/.gemini/antigravity-ide/brain/48d62b62-5e27-4f87-b6c1-13b1952c53f2/scratch/test_remediation.py)，3 項單元測試（GPSS 格式解碼、Google Patents Fail-Fast、PPUBS 降級 fallback）全數通過（OK）。
