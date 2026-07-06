# Bug Report & Workflow Retrospective: 異常偵測前案檢索經驗總結

**Date:** 2026-06-27
**Status:** Closed (2026-07-06 收敲) — 三類建議已被後續工作全數吸收:①`build_screening_table` 崩潰/分頁問題 → R13 拆分後檢索走 `patent_search` dispatcher(來源梯內建),表格組裝 landed 為 `screening_build.py` 離線腳本(原崩潰路徑不存在);②`patent_get_claim1` PPUBS 修復 → BR_20260628_figure_pdf_tooling §B/D PASS(`publication_number` 統一 + `ppubs_batch_get_claims` 實證可靠);③`gpatents` 警語/Fail-fast/單件限定 → SKILL.md §5(line 70)已載明;④五步 SOP + search_log → `flows/priorsearch.md` 固化資料夾結構 + `matrix-log.jsonl` + `search_audit` 機檢;⑤docxmcp Mode A 規範 → SKILL.md priorsearch `04_report/` 段已載。無殘留待修項。
**Context:** 執行「居家異常偵測與多模態感測技術」專利前案檢索與 Word 分析報告產出

本報告彙整了在執行專利檢索與分析報告編譯過程中所遭遇的摩擦點 (Friction Points)、克服的工作區 (Workarounds)，以及來自使用者的嚴格流程要求。這些經驗將作為優化 `patentmcp` 工具及其 Companion Skill 的重要養分。

---

## 1. 過程中的摩擦點與克服方法 (Friction Points & Workarounds)

### 摩擦點 1：GPSS 檢索匯出不穩定 (`build_screening_table`)
* **問題描述**：使用 `build_screening_table` 向 GPSS 系統請求時，若檢索結果數量過大（大於 50-100 件），或使用較為泛用的關鍵字（如單純的 `fall` 而非 `fall detection`），API 經常崩潰並回傳 `'str' object has no attribute 'get'` 或 `Expected JSON` 錯誤。這表示底層爬蟲拿到了錯誤頁面或 HTML 格式。
* **克服方法**：將查詢拆分為更精準的子條件（如加入多條件限縮）、分開指定資料庫（如 `US`, `CN`, `TW` 分開查），並改用 `purpose='minimal'` 降低欄位負載，成功迴避了崩潰。

### 摩擦點 2：CSV 資料清理與合併的雷區
* **問題描述**：嘗試使用 Shell 工具（如 `awk`, `sed`）直接處理包含摘要、獨立項等多行文本且帶有逗號及引號的 CSV 檔案時，極易導致欄位錯位與資料損壞。
* **克服方法**：放棄 Shell text processing，改為在 `run_command` 的 Sandbox 中撰寫 Python 腳本，利用標準的 `csv.DictReader` 與 `csv.DictWriter` 來進行安全、強健的 13 份 CSV 合併與去重。

### 摩擦點 3：US 專利 Claim 1 擷取失效 (`patent_get_claim1`)
* **問題描述**：針對 US 專利呼叫 `patent_get_claim1` 時，系統回報 `Granted patent document not found in PPUBS` 或 `Application document not found in PPUBS`。
* **克服方法**：啟動 Fallback 機制，改用 `gpatents_get` 工具至 Google Patents 提取完整的摘要與 Claims，並從中解析出 Claim 1。

### 摩擦點 4：Google Patents (gpatents) 極度敏感與限流 (403/503)
* **問題描述**：當嘗試使用 `gpatents_search` 進行批量 URL 查詢或用 `gpatents_download_figure` 批量下載代表圖時，迅速觸發 Google 的防爬蟲機制，遭遇 `403 Forbidden`（縮略圖權限阻擋）與 `503 Service Unavailable`（API 限流）。
* **克服方法**：遵循使用者嚴格的 Fail-Fast 規定，一旦遇到限流立刻停止該路徑，**絕不**使用自製腳本寫迴圈重試。

### 摩擦點 5：Word 報告組裝 (DOCX) 的原生限制
* **問題描述**：使用者嚴格禁止撰寫本地 Python/Bash 腳本來直接修改 `.docx` 的 XML（OOXML）或自行 ZIP 打包。
* **克服方法**：完全依賴 `docxmcp_document` (Mode A: `assemble`) 原生工具。建立標準的 `doc_dir` 結構（包含 `manifest.json`、`chapters/` 與 `assets/`），將 Markdown 與圖片交由 `docxmcp` 自行編譯。

---

## 2. 使用者的流程要求與 SOP 準則

在整個過程中，使用者做出了以下嚴格的流程要求，必須納入未來的 SOP：

1. **先發散後收斂的大池檢索 SOP**：
   * 必須使用「CPC + 關鍵字」的多種排列組合（例如 `(a & B & c) | d` 輪替），去 TIPO (GPSS/GNSS) 進行多次檢索，確保無遺漏。
   * 若單次組合檢索樣本數過大（例如超過 1000 件），不應全數納入，而必須加入更多條件限縮至合理處理成本範圍。
   * 將每次檢索的結果匯出 CSV，並在本地離線進行合併、去重與 AI 篩選。
   * 直到精選出「最相關的前 N 件核心專利」後，才可以針對這 N 件進行逐一下載完整專利檔與代表圖。
2. **詳實的檢索追蹤紀錄**：
   * 檢索報告中必須包含一個專屬表格（例如 `search_log.md`），詳實記錄每種檢索組合的邏輯、條件及命中數量，以供溯源。
3. **`gpatents` 使用禁忌**：
   * **絕對禁止**將 `gpatents` 相關工具作為批量搜尋的主力。
   * Google Patent 對爬蟲極度敏感，只能將其作為 GNSS / EPO / USPTO 皆失效時的**最後手段**，且僅限用於**單一檔案**的搜尋與下載。
4. **工具使用邊界（Anti-Scripts 規範）**：
   * 嚴禁以任何自製腳本（Python/Bash）替代或繞道原生 MCP 工具發送 API、重試 API 或處理 XML 檔案。遇到問題必須 Fail-fast 回報。
5. **計畫與規格變更需使用 `specbase`**：
   * 當需要發布或修改 Plan 時，必須使用 `specbase` 的原生 MCP 工具進行。

---

## 3. 改良建議：`patentmcp` 工具 (Tools)

* **`build_screening_table`**：
  * **增強錯誤處理**：當 GPSS 負載過大或回傳非 JSON 內容時，應攔截 HTML 錯誤，並提供清晰的 `Tool Error` 提示，而非拋出 Python Exception。
  * **隱式分頁處理**：對於命中數較大的查詢，工具內部應實作安全的延遲分頁抓取（Pagination with cooldown），以避免單次 Request Timeout 或被遠端 Drop。
* **`patent_get_claim1`**：
  * **修復 PPUBS 整合**：目前對 US 專利（無論 Granted 或 Application）皆頻繁回報 not found，需檢修其內部 PPUBS 查詢邏輯或 fallback 鏈的可靠性。
* **`gpatents_*` 工具群**：
  * **Schema 警語強化**：在 `description` 中必須強烈標註：「**WARNING: Google Patents is highly sensitive to scraping. Use ONLY as a last resort for single-file retrieval. DO NOT use for batch processing.**」

---

## 4. 改良建議：`patent-search` Companion Skill

* **寫入標準 SOP 工作流**：
  在 SKILL.md 中明文規定標準的專利分析五步法：
  1. **策略擬定**：制定 CPC + 關鍵字多條件排列組合矩陣。
  2. **批量檢索與匯出**：透過 GPSS/GNSS 執行組合，匯出多份 CSV，並維護 `search_log.md` 紀錄檢索邏輯與數量。
  3. **離線合併大池**：本地 Python 合併去重生成 `master_pool.csv`。
  4. **AI 精選過濾**：離線撰寫評分函數，挑選出 Top N 核心前案。
  5. **精準下載**：針對 Top N 單件取得完整 Claim 1 與代表圖。
* **納入 `gpatents` 限流認知與 Fail-fast 原則**：
  * 明確規範 `gpatents` 僅供單件 Fallback 使用，嚴禁批量迴圈呼叫。
  * 遭遇 API 失敗需立即停止並向使用者回報 (Fail-fast)，嚴禁 AI 擅自撰寫 `while True:` 或 `sleep()` 的腳本繞道。
* **強制 Docx 報告生成規範**：
  * 規定報告的 Word 生成必須整理出 `manifest.json` 與 `chapters/` 結構，並直接呼叫 `docxmcp_document`，嚴格禁止操作 XML。
