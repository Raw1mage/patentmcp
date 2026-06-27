# Tasks: analysis_batch-assets

## T1 — pyproject.toml Dependency Update
- [x] T1.1 Add matplotlib and pandas to dependencies list in pyproject.toml.
- [x] T1.2 Rebuild Docker image to verify dependencies are successfully locked.

## T2 — Full Claims Retrieval (patent_get_claim1)
- [x] T2.1 Add `full: bool = True` argument to `patent_get_claim1`.
- [x] T2.2 Update `extract_claim1_text` to support bypassing the 1000-character truncation.
- [x] T2.3 Apply truncation if `full=False` across all client fallbacks.

## T3 — Batch Figures Downloader (patentmcp_batch_download_figures)
- [x] T3.1 Expose `patentmcp_batch_download_figures` tool.
- [x] T3.2 Implement local `.tmp/cooldown.json` (or token workspace-based cooldown) caching to record 503 failures.
- [x] T3.3 Automatically skip downloading assets if their cooldown timer is active.
- [x] T3.4 Stage downloaded images in token store and return relative file handles.

## T4 — Pool Analysis Visualizer (patentmcp_analyze_pool)
- [x] T4.1 Expose `patentmcp_analyze_pool` tool.
- [x] T4.2 Fetch pool metadata in batch (Jurisdiction, Date, CPC, Assignee, Category) from BQ/cache.
- [x] T4.3 Generate 5 standard HSL-themed statistic charts (country, trend, cpc, assignee, category) using matplotlib and pandas.
- [x] T4.4 Implement Archimedean spiral word cloud renderer using pure Matplotlib, with local stopword parsing.
- [x] T4.5 Store all 6 charts in token store and return download handles.

## T5 — Verification & Handoff
- [x] T5.1 Write automated script to test all three endpoints.
- [x] T5.2 Verify that visual outputs (including wordcloud.png) comply with high-quality HSL standards.
