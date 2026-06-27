# Error States: Patent PDF Fetch

## Error Catalogue

| Code | Meaning | Recovery / Fallback |
|---|---|---|
| `NOT_FOUND` | Publication not in EPO/Google | Stop; fallback to text-only description. |
| `THROTTLED` | 429 Too Many Requests | Back off according to `min_interval` or `Retry-After`. |
| `FORBIDDEN` | 403 Forbidden (Guessed Path) | Do not retry; indicates path pattern error. |
| `SERVICE_UNAVAILABLE` | 503 Service Unavailable | Short exponential backoff (max 3 retries). |
| `DOWNLOAD_FAILED` | Binary download interrupted | Retry once or mark as failed attempt. |
| `PN_PARSE_ERROR` | Malformed publication number | Return error; do not retry. |
