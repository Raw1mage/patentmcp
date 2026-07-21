# Proposal: batch-claims-exporter

## Why

- **痛點**：
  1. 目前 Agent 在需要批量獲取代表專利的獨立請求項 (Claim 1) 以進行白話技術分析時，必須以迴圈方式多次調用單一查詢工具 `patent_get_claim1`。這不僅造成效率低下，且極易在進入 Google Patents 爬蟲降級時觸發 Google 503 阻斷。
  2. 現有單一查詢 `patent_get_claim1` 中，台灣（TW）、美國（US）與中國（CN）專利未優先向 TIPO (GPSS) 系統查詢，且缺乏 EPO (OPS) 官方 claims 讀取整合，過度依賴脆弱的 Google Patents Scraper 爬蟲。
  3. 缺乏一個與 `docxmcp` 規格相容的批次 Claim 匯出工具及對應的 CLI 進入點，使得 Agent 在本地常有編寫臨時腳本繞道的違規行為。
- **機會**：
  - 新增 `ppubs_batch_get_claims` 原生 MCP 工具，將輸出登錄於 `token_store` 以供 `docxmcp` 透過 token 參考讀取。
  - 將路由排序優化為「TIPO (GPSS) 優先（TW/US/CN）-> 官方 API / BQ (USPTO PPUBS / EPO OPS / BigQuery) -> Google Patents (最末底線)」。
  - 擴充 `EPOClient` 實作官方 `/claims` 端點的解析，徹底降低對 Google Patents 爬蟲的依賴。

## Original Requirement Wording (Baseline)

- "對。先解析這個claim exporter的狀況是什麼"
- "問題是為什麼總是要把google patent放在優先使用的清單中呢？永遠優先使用tipo"
- "EPO>google"

## Requirement Revision History

- 2026-06-27: Initial draft created via plan-init.ts.
- 2026-06-27: Revised to establish TIPO-first routing, EPO claims integration, and batch tokenized JSON output.

## Effective Requirement Description

擴充 `patentmcp`，實作高階批次專利獨立請求項 (Claim 1) 擷取工具。該工具應優先透過 TIPO (GPSS) 官方 API 讀取全球專利，降級時依序使用 USPTO/EPO 官方 API，最後才是 Google Patents；提供對應的 CLI 命令與 token 儲存機制。

## Scope

### IN
1. **優化 `patent_get_claim1` 與優先順序 (TIPO-First)**：
   - 針對任何專利，若為 TW、US、CN 專利，一律優先使用 TIPO (GPSS) 查詢。
   - 若 GPSS 查無或失敗，降級使用各國官方管道（US 使用 USPTO PPUBS；EP 使用 EPO OPS；其他使用 BigQuery）。
   - Google Patents 爬蟲為最末底線備用（EPO 優先級大於 Google Patents）。
2. **擴充 `EPOClient` 支援 Claims**：
   - 在 `src/patent_mcp_server/epo/client.py` 中新增 `claims(pub)` 實作，讀取 `/published-data/publication/docdb/{docdb}/claims` 端點。
   - 解析 BadgerFish JSON 格式，提取 Claim 1 原文。
3. **新增 `ppubs_batch_get_claims` MCP 工具**：
   - **輸入**：`patent_numbers` (專利號清單)。
   - **邏輯**：循序（或限制併發並有延遲，防官方 API 拒絕）批次查詢 Claim 1。
   - **輸出**：返回專利號與 Claim 1 的映射 JSON；同時將該 JSON 寫入 `token_store` 並返回 docxmcp 風格的 token 下載 handle（如 `claims.json`）。
4. **新增 CLI 進入點**：
   - 擴充 `patents.py` 的 `main()`，支援 `--export-claims` 與 `--output` 參數，允許在 terminal 執行批次匯出。

### OUT
- 本次不重構除了 Claim 1 以外的完整專利書目 (biblio) 批次匯出。
- 不提供 TIPO、USPTO 或 EPO 帳號密碼登錄工具，API 金鑰統一由環境變數讀取。

## Non-Goals

- 本工具不在本機實作 claims 的中文/英文機器翻譯。

## Constraints

- 批次查詢單次專利號上限為 100 件。
- 遵循專案環境變數中的限流與冷卻時間設定。

## What Changes

- 修改 `src/patent_mcp_server/epo/client.py` 以擴充 `claims()` API 查詢。
- 修改 `src/patent_mcp_server/patents.py` 以優化路由順序、新增 `ppubs_batch_get_claims` 工具與 CLI 參數支援。

## Capabilities

### New Capabilities
- `ppubs_batch_get_claims`: 批次專利獨立請求項 (Claim 1) 擷取工具。
- `EPOClient.claims`: 歐洲專利局官方 Claims API 查詢。

### Modified Capabilities
- `patent_get_claim1`: 改為 TIPO 優先，且降級至 EPO 優先於 Google Patents。

## Impact

- 消除 Agent 撰寫臨時 Python 爬蟲腳本的需求，確保專利 Claims 分析流程的合規性與連線穩定度。
