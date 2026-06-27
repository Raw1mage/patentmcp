# Error States: Batch Claims Exporter

## Error Catalogue

| Code | Meaning | Recovery / Fallback |
|---|---|---|
| `EPO_API_ERROR` | EPO OPS API connection or credential failure | Log warning; fallback to BigQuery/Google Patents. |
| `EPO_CLAIMS_PARSE_FAILED` | Failed to parse BadgerFish JSON format | Return empty claim; log detail; fallback to scraper. |
| `GPSS_QUERY_FAILED` | TIPO GPSS query failed | Proceed to next official fallback (USPTO/EPO). |
| `BATCH_LIMIT_EXCEEDED` | Input patent count exceeds the limit of 100 | Throw error response; reject request. |
