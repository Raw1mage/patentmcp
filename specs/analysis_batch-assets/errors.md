# Error States: Pool Analysis & Batch Assets Retrieval

## Error Catalogue

| Code | Meaning | Recovery / Fallback |
|---|---|---|
| `COOLDOWN_ACTIVE` | Asset is in 503 cooldown period | Skip downloading; log warning; return skipped status. |
| `METADATA_FETCH_FAILED` | Failed to retrieve patent pool metadata | Attempt individual scraper fallback; return partial data. |
| `PLOT_FAILED` | Matplotlib failed to render charts | Return error; fallback to text-only report. |
| `TOKEN_STORE_ERROR` | Unable to stage output images | Log error; check directory permissions. |
