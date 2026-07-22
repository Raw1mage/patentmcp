# Errors: patentmcp_classification-bulk-export

## Error Catalogue

分類軸批次匯出走 GPSS 官方端點,官方 miss 即真 0 **絕不退爬蟲**(DD-5)。
所有錯誤以結構化 envelope 回傳(`{success, error_code, message, provenance[], ...}`),
非 exception;呼叫端以 `error_code` 分流。實作見 `search_dispatcher.py::bulk_export` /
`_bulk_pull_gpss`,前端見 `patents.py::patent_bulk(source="gpss")`。

| Code | Condition | Surface | Recovery |
| ---- | --------- | ------- | -------- |
| `INVALID_PARAMS` | 未給任一分類軸(ipc/cpc/uspc 全空) | `bulk_export` 前置檢查即回,`gpss_client.search` **零呼叫**;`message="分類軸批次匯出需至少一個分類軸 (ipc/cpc/uspc)"` | 呼叫端補上 ipc/cpc/uspc 至少一軸後重呼。純分類軸語義的硬約束(DD-4) |
| `GPSS_NOT_CONFIGURED` | `gpss_client.configured()` 為 False(`GPSS_USER_CODE` 未設) | `bulk_export` fail-fast,零 backend 呼叫;`provenance=[{source:gpss,status:skipped,reason:not_configured}]`;`message="批次匯出僅走 TIPO GPSS 官方端點,需設 GPSS_USER_CODE"` | 於容器/cfg 層設 `GPSS_USER_CODE` 後重呼。**不 fallback** 至 EPO/PPUBS/爬蟲(DD-5) |
| `GPSS_ERROR` | GPSS 端非 "no record found" 的硬失敗(HTTP 4xx/5xx、傳輸例外);第一頁即失敗 → `_bulk_pull_gpss` 拋 `BackendError` | `bulk_export` catch 後回 `error_code=GPSS_ERROR`;`provenance=[{source:gpss,status:error,reason:http_error:NNN|<msg>}]`;reason 由 `_error_reason` 抽出 `http_error:<code>` | 檢查 GPSS 端點/配額/網路後重呼。單頁 transient 錯誤在 `_bulk_pull_gpss` 內有 per-page 重試(`_BULK_PAGE_RETRIES=3`,exp-backoff 2s/4s/8s),耗盡才升為 `GPSS_ERROR` |
| (真 0,非錯誤) | GPSS 回 `status=success` + "no record found" boilerplate(該分類軸下確實無專利) | `success=True` + `records=[]` + `source=gpss` + `total=0`;`provenance` 含 `{status:miss,reason:zero_hits}`;**無 `error_code`**;provenance 永不含 gpatents/scraping | 這是**真 0**,不是失敗——該分類軸下真的沒有專利。呼叫端不得據此退爬蟲或重試其他來源(DD-5 天條) |
| (分頁中斷) | 分頁途中某頁 transient error 或回空,但**先前頁已累積 records** | `success=True` + 已累積的 partial records;`provenance` 記該頁 `status=error`/`axis_exhausted`;`total` 為 GPSS 回報總數 | partial 為有效結果(已入 patentdb)。`next_skip` 可續拉;patentdb `put()` COALESCE-only 使續拉 idempotent(重跑不覆寫非空 row) |
