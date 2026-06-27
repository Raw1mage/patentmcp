# Spec: Patent Pool Analysis and Batch Assets Retrieval

## Purpose
Optimize patent claims retrieval and establish stable tools for batch downloading representative figures and analyzing patent pools with high-quality visualization, including local text-mining word clouds.

## Requirements

### Requirement: Full Claims Retrieval
The system MUST allow users to retrieve the full, untruncated Claim 1 text.

#### Scenario: Retrieval with full=True
- Given a valid publication number.
- When `patent_get_claim1` is called with `full=True`.
- Then the full text of Claim 1 is returned without character truncation.

### Requirement: Batch Figure Downloading
The system MUST allow batch downloading of representative figures with 503 cooldown handling.

#### Scenario: Download with Cooldown
- Given a list of publication numbers.
- When `patentmcp_batch_download_figures` is called.
- Then figures are downloaded to the token store, and if 503 is encountered, it is recorded and skipped.

### Requirement: Pool Analysis
The system MUST support visual and statistical analysis of a group of patents, including key tech word clouds.

#### Scenario: Render Pool Charts
- Given a list of publication numbers.
- When `patentmcp_analyze_pool` is called.
- Then country, trend, CPC, assignee, category charts, and a matplotlib-based tech word cloud are saved to the token store.

## Acceptance Checks
- [ ] Claim 1 text matches full text without trailing `...` when full=True.
- [ ] Figures are downloaded to the token store directory.
- [ ] 6 HSL-themed PNG files (including `wordcloud.png`) are outputted in the token store.
