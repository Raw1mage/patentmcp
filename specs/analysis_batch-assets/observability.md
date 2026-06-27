# Observability: Pool Analysis & Batch Assets Retrieval

## Events
- `BATCH_DOWNLOAD_START`: Logged when batch downloading starts.
- `COOLDOWN_SKIP`: Logged when an asset is skipped due to active 503 cooldown.
- `PLOT_START`: Logged when pool analysis plotting starts.
- `PLOT_COMPLETE`: Logged when 5 charts are rendered and stored.

## Metrics
- `batch_download_success_rate`: Percentage of successfully downloaded figures.
- `pool_analysis_latency_ms`: Time taken to fetch metadata and plot charts.

## Logs
- **Level**: `INFO` for complete runs, `WARNING` for skipped assets/partial metadata, `ERROR` for plotting/store failures.
- **Context**: Every log includes `publication_numbers` list size.
