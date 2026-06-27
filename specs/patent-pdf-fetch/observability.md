# Observability: Patent PDF Fetch

## Events
- `RESOLVE_URL_START`: Logged when starting resolution (EPO/Google).
- `DOWNLOAD_START`: Logged when a binary stream is initiated.
- `STORAGE_COMPLETE`: Logged when file is staged in token-store.
- `FETCH_SUCCESS`: Final success event with source attribution.
- `FETCH_FAILURE`: Final failure event with error code.

## Metrics
- `pdf_fetch_success_rate`: Percentage of successful downloads by source.
- `pdf_fetch_latency_ms`: Total time from request to handle delivery.
- `throttling_cooldown_active`: Gauge of active backoff state for EPO/Google.

## Logs
- **Level**: `INFO` for successful acquisitions, `WARNING` for throttled attempts/fallbacks, `ERROR` for terminal failures.
- **Context**: Every log should include the `publication_number`.
