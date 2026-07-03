# Errors: patentmcp_search-dispatcher

## Error Catalogue

| Code | Condition | Surface | Recovery |
| ---- | --------- | ------- | -------- |
| `INVALID_PARAMS` | 無任何檢索軸(cpc/ipc/uspc/keyword/applicant/pub_number 全空)或參數格式錯誤 | `{success:false, error_code, message}`;不打任何後端 | 補上至少一個檢索軸再呼叫 |
| `SCRAPING_REQUIRED` | 官方梯(GPSS/EPO/PPUBS)全 miss 且 `allow_scraping=False` | `{success:false, error_code, provenance[官方三級明細], suggestion}` | 取得使用者明確口頭同意後帶 `allow_scraping=True` 重呼叫 |
| `ALL_SOURCES_MISS` | 含授權尾級在內全部 miss | `{success:false, error_code, provenance[全四級]}` | 調整查詢軸(換分類/放寬日期/改關鍵字);缺口按 provenance 逐級稽核 |
| `AXIS_CONFLICT` | 互斥軸組合(如 uspc + databases 指定非 US 庫) | `{success:false, error_code, message}` fail-fast | 修正軸組合 |
| `BACKEND_ERROR:<source>` | 單一梯級 HTTP/quota 錯誤(EPO 403 quota、GPSS 5xx…) | provenance 該級 `status:"error", reason:"http_error:<code>"`,梯級繼續往下 | 無需處理;若最終失敗按上兩碼恢復 |
| (uspto_patents) search method 拒收 | `method in {ppubs_search_patents, ppubs_search_applications}` | `{success:false, message:"search methods retired — use patent_search"}` | 改呼叫 `patent_search` |
