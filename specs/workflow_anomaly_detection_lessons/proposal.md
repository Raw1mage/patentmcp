# Proposal: workflow_anomaly_detection_lessons

## Why

在執行「居家異常偵測與多模態感測技術」專利前案檢索時，暴露出 `patentmcp` 部分 API 與流程的穩定性問題，需要對這些元件進行加固：
1. **GPSS 檢索大池不穩定**：當 `build_screening_table` 檢索結果過大（> 50-100 件）或關鍵字太寬泛時，API 會返回 HTML 或非 JSON 頁面，導致 `'str' object has no attribute 'get'` 崩潰。
2. **US 專利 Claim 1 取得失效**：對 US 專利執行 `patent_get_claim1` 時，常因 PPUBS 無法查詢而報錯，缺乏自動降級至 `gpatents` 抓取與解析的 Fallback 機制。
3. **Google Patents 限流與爬蟲安全性**：批量使用 `gpatents_*` 工具容易遭 Google 限流 (403/503)。工具端需要實現 Fail-fast 阻斷，並在 Schema 與 SOP 中強制將 Google Patents 限制為「單件已知專利下載 fallback 的最後手段」，嚴禁批量爬取。
4. **CSV 處理與 Word 報告組裝雷區**：使用 Shell 腳本處理多行 CSV 易損壞資料；且自製腳本打包 DOCX XML 風險高。需規範本地 CSV 合併僅能使用 Python `csv` 模組，DOCX 報告編譯必須使用 `docxmcp` 的 `assemble` 流程。

## Original Requirement Wording (Baseline)

- "用specbase mcp將這個bug report分析設計成plan"
- 來自 [BR_20260627_anomaly_detection_workflow_lessons.md](file:///home/pkcs12/projects/patentmcp/issues/BR_20260627_anomaly_detection_workflow_lessons.md) 的各項摩擦點與改進建議。

## Requirement Revision History

- 2026-06-27: 根據檢索 retrospectives 建立初始計畫。

## Effective Requirement Description

1. **加固 `build_screening_table`**：
   * 實現對 GPSS 響應的異常攔截，回傳乾淨的 Tool Error，避免 Python Exception。
   * 內部實作延遲分頁抓取（Pagination with cooldown），以處理大結果集。
2. **實現 `patent_get_claim1` 降級機制**：
   * 當 PPUBS 查詢失敗時，自動降級呼叫 `gpatents_get` 獲取 claims，並從中解析出第一項權利要求。
3. **限制與保護 `gpatents` 工具**：
   * 於 `gpatents_*` 工具 Schema 加上強烈警告，明文禁止批量呼叫。
   * 引入 Fail-fast 機制，若遭遇 403/503/429 立即中斷執行。
4. **規範 SOP 指引與 Companion Skill**：
   * 更新 `patent-search` 的 Companion Skill，包含檢索矩陣日誌、Python CSV 合併去重範例、以及 `docxmcp` 報告組裝流程。

## Scope

### IN
- `vendor/patents-mcp/src/patent_mcp_server/patents.py`：修改 `build_screening_table` 與 `patent_get_claim1`。
- `vendor/patents-mcp/src/patent_mcp_server/screening_table.py`：配合分頁與錯誤攔截調整。
- `gpatents` 相關工具的 Schema 說明與限流阻斷邏輯。
- 更新與同步 `skills/` 下的專利檢索指引。

### OUT
- 不實作繞過 Google Patents 驗證碼/限流的 Proxy 爬取技術。
- 不提供 docxmcp 以外的 DOCX 原生 OOXML 讀寫庫。

## Non-Goals

- 不把 Google Patents 作為主要检索入口。
- 不修改 GPSS 底層的權限控制與 OAuth 機制。

## Constraints

- 任何二進位或大型 CSV 產物必須落地至 token-store，模型 context 僅接收 handle。
- Google Patents fallback 的呼叫頻率必須受到嚴格限流保護。

## What Changes

- 修改 `patents.py` 的 `build_screening_table` 處理非 JSON 回應之 Exception，並引入分頁。
- 修改 `patents.py` 的 `patent_get_claim1` 增加降級至 `gpatents` 的邏輯。
- 更新 `gpatents` 工具的 `description` 字串。
- 修改專利檢索 Companion Skill 文件（如 `skills/patent-practitioner-workflow.md` 等）。

## Capabilities

### New Capabilities
- **GPSS 分頁與冷卻**：能在不超時與不觸發大流量阻斷的情況下安全拉取超過 100 件以上的專利。
- **Claim 1 降級路由**：PPUBS 與 Google Patents 雙路徑備援。

### Modified Capabilities
- **gpatents_*** 安全防護：遭遇封鎖時自動觸發 Fail-fast 中斷，保護 API 配額。

## Impact

- `vendor/patents-mcp/src/patent_mcp_server/patents.py`
- `vendor/patents-mcp/src/patent_mcp_server/screening_table.py`
- `skills/patent-practitioner-workflow.md`
