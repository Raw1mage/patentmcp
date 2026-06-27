# Error States: Anomaly Detection Workflow Lessons Remediation

## Error Catalogue

| Code | Meaning | Recovery / Fallback |
|---|---|---|
| `JSON_DECODE_ERROR` | GPSS 回應非 JSON 格式（如 HTML 錯誤頁面） | 攔截例外，停止解析，向用戶返回包含錯誤詳情的 Tool Error。 |
| `PPUBS_NOT_FOUND` | PPUBS 中查無該 US 專利 | 啟動降級路由，呼叫 `gpatents_get` 嘗試解析該案的第一獨立項。 |
| `GPATENTS_403_FORBIDDEN` | 遭遇 Google Patents 封鎖 | 立即觸發 Fail-fast 熔斷，不重試，傳回 `Blocked` 例外。 |
| `GPATENTS_503_UNAVAILABLE` | 遭遇 Google Patents 限流 | 立即觸發 Fail-fast 熔斷，不重試，傳回 `Throttled` 例外。 |
| `GPSS_TIMEOUT` | GPSS 分頁請求超時 | 重新嘗試該頁面一次，若再度超時則以已取得的部分資料結案並發出警告，或中止回報。 |
