# Observability: Batch Claims Exporter

## Events
- `BATCH_EXPORT_START`: Logged when batch claims export starts.
- `EPO_CLAIMS_FETCH`: Logged when fetching claims from EPO OPS.
- `TIPO_PRIORITY_ROUTE`: Logged when routing US/TW/CN patents to TIPO GPSS.
- `BATCH_EXPORT_COMPLETE`: Logged when export JSON is staged and returned.

## Metrics
- `batch_export_latency_ms`: Total execution time of the batch export.
- `claims_fetch_source_distribution`: Counters for claims retrieved via GPSS, PPUBS, EPO, BigQuery, or Google scraper.

## Logs
- **Level**: `INFO` for start/end, `WARNING` for fallbacks triggered, `ERROR` for critical staging or credential failures.
