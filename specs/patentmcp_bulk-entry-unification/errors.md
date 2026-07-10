# Errors: patentmcp_bulk-entry-unification

## Error Catalogue

| Code | Condition | Surface | Recovery |
| ---- | --------- | ------- | -------- |
| INVALID_PARAMS | source 缺失/非 gpss\|epo;或該源缺必要檢索軸 | `{success:false, error_code, message}` | 補 source / 補至少一個硬軸 |
| GPSS_NOT_CONFIGURED | source=gpss 但無 GPSS_USER_CODE | 同上 | 設憑證或改 source=epo |
| EPO_NOT_CONFIGURED | source=epo 但無 EPO_CONSUMER_KEY/SECRET | 同上 | 設憑證或改 source=gpss |
| GPSS_ERROR / EPO_ERROR | 後端 BackendError | 同上 + provenance 記 error reason | 讀 message;EPO 可依 next_skip 續撈已落地部分 |
| TOOL_RENAMED | 呼叫三個已下架 bulk 工具 | `{success:false, error_code:"TOOL_RENAMED", use:"patent_bulk", note}` | 依 note 把參數搬到 patent_bulk |
