# Event: MCP Screening Export switched to CSV

## Scope
- `patentmcp` `build_screening_table` export format.
- PatentWorks screening delivery contract and related spec docs.

## Requirement
- 更新 MCP 功能，匯出 CSV 檔，不要 xlsx 檔，讓 Agent 分析更友善。

## Key Decisions
- `build_screening_table` default filename changed from `screening.xlsx` to `screening.csv`.
- Screening table rendering now uses Python stdlib `csv` and UTF-8 bytes instead of `openpyxl`.
- Removed `openpyxl` and `et-xmlfile` from dependency metadata/lockfile because CSV output needs no xlsx writer.
- Synchronized README, PatentWorks flow docs, practitioner workflow, architecture SSOT, and plan artifacts to describe CSV as the screening delivery invariant.

## Verification
- `python3 -m compileall src` passed under `vendor/patents-mcp`.
- `PYTHONPATH=src` smoke test verified CSV header rendering, comma quoting, and newline quoting.
- Targeted grep found no remaining `xlsx` / `openpyxl` contract references under `vendor/patents-mcp`, `specs`, or `skills`.
- Architecture Sync: updated `specs/architecture.md` because the MCP table delivery contract changed.

## Issues
- `uv` is not installed in the environment, so `uv lock` could not be regenerated automatically; `uv.lock` was updated manually to remove the now-unused `openpyxl` dependency entries.
- Working tree already contains unrelated modified/untracked files outside this change scope; they were not reverted.
