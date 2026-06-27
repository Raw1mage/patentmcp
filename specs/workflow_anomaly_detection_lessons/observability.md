# Observability: Anomaly Detection Workflow Lessons Remediation

## Events
- `GPSS_PAGE_FETCH_START`: 開始分頁拉取 GPSS 資料。
- `GPSS_PAGE_FETCH_SUCCESS`: 成功拉取某一頁的 GPSS 資料。
- `GPSS_DECODE_ERROR`: 解碼 GPSS 回應失敗（如 HTML 錯誤頁面）。
- `CLAIM1_PPUBS_FAIL`: PPUBS 查詢 Claim 1 失敗，啟動 Google Patents 降級。
- `CLAIM1_GPATENTS_SUCCESS`: 成功透過 Google Patents 備援取得 Claim 1。
- `GPATENTS_BLOCKED`: Google Patents 請求遭到阻斷 (403/503/429)。

## Metrics
- `gpss_pages_fetched_count`: 單次查詢中已拉取的 GPSS 分頁數量。
- `claim1_fallback_ratio`: 使用 Google Patents 降級取得 Claim 1 的比例。
- `gpatents_block_counter`: 觸發 Google 限流熔斷的次數。

## Logs
- **Level**: `INFO` 記錄分頁拉取與成功降級；`WARNING` 記錄 PPUBS 遺失與開始降級的行為；`ERROR` 記錄解碼失敗與 Google 熔斷中斷。
- **Context**: 記錄日誌時必須附帶 `publication_number` 或檢索關鍵字。
