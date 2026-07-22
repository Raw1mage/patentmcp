# Observability: mcp_r16-domain-kb

## Events

- `kb_query` / `kb_get` 呼叫走 FastMCP 標準 request log（stderr，logging.INFO）——工具名 + 執行時間由框架記錄，無額外自訂 log line（deterministic serving，無隱藏狀態）。
- `KB_UNAVAILABLE` envelope 本身是可觀測信號：payload 帶 message + remedy，caller 端即可診斷（env 未設 vs 檔案缺失 vs sqlite 開啟失敗，message 區分）。

## Metrics

- `matchMode` 分布（fts / like-scan / hybrid）——payload 自帶，caller/agent 可聚合觀察 CJK 短查詢降級比率。
- `total` vs `limit`——查詢命中量信號，corpus 成長觀測。
- 測試面：`tests/test_kb_tools.py` 全綠 = serving 契約健康；兩門一致性（TV-6）= store 無 fork 的持續驗證點。
