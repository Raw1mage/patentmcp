# Handoff: Pool Analysis & Batch Assets Retrieval

## Execution Contract
This implementation follows the `analysis_batch-assets` plan. The goal is to provide a unified batch-assets and pool analysis toolset in `patents.py`. Claim 1 text retrieval must support full retrieval, batch downloading must handle 503 HTTP errors gracefully with cooldowns, and pool analysis must generate 5 HSL-themed charts in the token store.

## Required Reads
- `vendor/patents-mcp/src/patent_mcp_server/patents.py`: Main entry point for tool implementation.
- `vendor/patents-mcp/pyproject.toml`: Dependency verification.
- `specs/architecture.md`: Delivery contract alignment.

## Stop Gates In Force
- Stop if BQ dataset query limits are exceeded during metadata batch retrieval.
- Stop if matplotlib rendering output path is not writable inside the Docker container environment.

## Execution-Ready Checklist
- [ ] Matplotlib and Pandas are successfully installed in the container python env.
- [ ] Token store path is correctly configured and writable.

## Downstream Consumer: docxmcp
The primary consumer of this tool's output is `docxmcp` templates which load these charts by reference using token handles.
