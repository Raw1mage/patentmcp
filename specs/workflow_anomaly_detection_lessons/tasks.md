# Tasks: Anomaly Detection Workflow Lessons Remediation

## T1 — GPSS Resilience & Pagination

- [x] T1.1 在 `patents.py` 的 `build_screening_table` 中，增加對 GPSS API 回應的 `JSONDecodeError` 攔截，回報乾淨的 Tool Error。
- [x] T1.2 於 `build_screening_table` 內實作以 50 件為單位的分頁拉取機制。
- [x] T1.3 在分頁請求之間引入 1.0 秒的冷卻時間（Cooldown Sleep），以防觸發 GPSS 端的大流量封鎖。
- [x] T1.4 將分頁拉取的結果於 Server 端進行安全合併，再導向 Token Store CSV 落地。

## T2 — Claim 1 Fallback Chain

- [x] T2.1 在 `patents.py` 的 `patent_get_claim1` 中攔截 PPUBS 的 `Granted/Application document not found` 錯誤。
- [x] T2.2 於失敗時降級呼叫 `gpatents_get` 獲取完整專利 Claims 內容。
- [x] T2.3 實作專利的 Claim 1 匹配與正則抽取邏輯，將抽取結果正確返回給呼叫端。

## T3 — Google Patents Scraper Guard

- [x] T3.1 於 `gpatents` 底層客戶端中檢測 HTTP `403`、`503` 與 `429` 狀態碼，一經發現立即拋出例外阻斷。
- [x] T3.2 修改 `gpatents_search` 等工具的 Schema 描述，加入強烈警告（禁止批量爬取，僅限單件 fallback 用途）。
- [x] T3.3 在工具內部實作單 flight 熔斷，防止多執行緒並行發送請求。

## T4 — Companion Skill Updates

- [x] T4.1 編輯專利檢索 Companion Skill 文件 `skills/patent-practitioner-workflow.md`。
- [x] T4.2 新增「先發散後收斂」五步檢索 SOP、`search_log.md` 檢索日誌格式規範。
- [x] T4.3 新增在沙盒中利用 Python `csv` 模組進行 CSV 合併去重的範例代碼與指引。
- [x] T4.4 寫入 DOCX 報告編譯必須使用 `docxmcp_document` 進行 assemble，嚴禁手動 XML/ZIP 讀寫的限制。

## T5 — Tests & Smoke Verification

- [x] T5.1 撰寫 GPSS 回傳無效/HTML 資料時的單元測試，驗證工具是否優雅返回 Error 而不崩潰。
- [x] T5.2 測試 US 專利號在 PPUBS 失效時是否能順暢經由 Google Patents 降級取得 Claim 1。
- [x] T5.3 驗證分頁拉取大於 50 件專利時，合併產生的 CSV 其格式完全正確，可被 Python 解析。
