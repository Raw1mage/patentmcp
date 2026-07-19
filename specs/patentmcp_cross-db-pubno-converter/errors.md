# Errors: patentmcp_cross-db-pubno-converter

## Error Catalogue

| Code | Condition | Surface | Recovery |
| ---- | --------- | ------- | -------- |
| （回空 list） | `to_epo_variants` / `patentdb_key_variants` 無法解析國碼/號形 | 回 `[]`（非 raise，非猜測號） | 呼叫端見空 list → fail fast，換來源或報 miss |
| （回 None） | `to_docdb` 底層 regex 不匹配（保留既有語義） | 回 `None` | 呼叫端跳過該號，記 provenance |
| （原樣返回） | `to_patentdb_key` 對無國碼字串 | country 預設 US（保留既有 `normalize_pubno` 行為，向後相容） | 不改變既有行為；DD-31 已修外國碼誤掛 |

> converter 是純函式格式轉換，**不 raise 例外**（除非傳入 None 之類型別錯誤）；歧義一律回 variants list，
> 無法解析回空 list / None，**絕不 silent fallback 到猜測號**（DD-2）。呼叫端負責 fail fast。
