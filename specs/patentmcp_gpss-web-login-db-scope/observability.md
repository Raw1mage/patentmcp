# Observability: patentmcp_gpss-web-login-db-scope

## Events

- `set_search_databases` 進入/存檔/跳回各步驟寫 `logger.info`（含 dbs、設定頁 URL、存檔 POST 狀態），比照 `adv_search.py` 的 `_dump` pattern。
- harvest 前若因 `databases` 觸發 set_search_databases，`provenance` 追加 `{step:"set_dbscope", ok, dbs}` 一筆，讓呼叫端可見庫範圍已鎖。

## Metrics

- 設定頁存檔往返成功率（`GPSS4_DBSCOPE_FAILED` 發生率）——監測 GPSS4 設定頁改版導致的逆工失效。
- `databases` 指定 vs 撈回結果國別純度（CN 純源池：非 CN 前綴 pat_no 佔比應為 0）——驗證檢索端母體邊界。
