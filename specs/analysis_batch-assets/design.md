# Design: Patent Pool Analysis & Batch Assets Retrieval

## Context
Existing `patent_get_claim1` truncates results to 1000 characters. Users need full text for regulatory analysis. Additionally, downloading multiple figures manually triggers Google 503 blocks, and plotting pool charts requires custom client-side python scripts. Users also need a cost-effective, local word cloud visualization of key technical features from the patent pool.

## Goals / Non-Goals
- **Goals**: Full claim 1 flag, batch figure downloader with cooldown skip cache, HSL-themed 6-chart generator (including self-rendered wordcloud) in token store.
- **Non-Goals**: Custom plotting config parameters, PDF OCR processing, external wordcloud library dependencies.

## Risks / Trade-offs
- **Risk**: Google IP ban during batch image fetch.
- **Mitigation**: Implement a local `.tmp/cooldown.json` to skip failed assets for 10 minutes.
- **Risk**: WordCloud overlap or slow rendering during Matplotlib plotting.
- **Mitigation**: Use an optimized Archimedean spiral search with simple bounding box collision detection in Python.

## Critical Files
- `vendor/patents-mcp/src/patent_mcp_server/patents.py`: Main entry point for tool exposure and implementation.
- `vendor/patents-mcp/pyproject.toml`: Addition of `matplotlib` and `pandas`.

## Decisions
- **DD-1**: Figures and charts will be stored inside the current session token store, returning URLs adhering to R2 File Transfer.
- **DD-2**: Fall back to BigQuery BQ query where possible for fast metadata fetch of the patent pool.
- **DD-3**: Word cloud text parsing uses Title + Abstract + Claim 1, with a local stopword filter removing common patent phrases. No LLM tokens will be consumed for this count.
