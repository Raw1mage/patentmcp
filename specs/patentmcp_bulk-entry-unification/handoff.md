# Handoff: patentmcp_bulk-entry-unification

## Execution Contract

- 交付:`patent_bulk` 統一入口(dispatcher `bulk()` + MCP wrapper)、三舊工具 stub、測試三檔全綠、SKILL.md §5 同步、三 BR 歸檔。
- Done = tasks.md 全勾 + `pytest tests/` 零 fail + BR 歸檔至 issues/closed/(BR_20260628 依驗證 B 結果決定 close 或留 REOPENED)。

## Required Reads

- `plans/patentmcp_bulk-entry-unification/design.md`(DD-1..DD-7)
- `src/patent_mcp_server/search_dispatcher.py`(bulk_export :301 / bulk_harvest :450 / epo_bulk_harvest :673 / _keyword_to_cql :484)
- `src/patent_mcp_server/patents.py`(三舊 wrapper :2796/:2871/:2925、_TOOL_RENAMED_ENVELOPE :2995)
- `tests/test_tool_renamed_stubs.py`(stub 測試模式)

## Stop Gates In Force

- 不得對真實 GPSS/EPO 端點發批量請求(測試一律 Fake client;額度硬閘)
- 不得新增跨源 fallback(DD-1;使用者天條)
- SKILL.md delegation-clauses sentinel 區塊(line 183-189)不得破壞

## Execution-Ready Checklist

- [x] 三張 BR 已讀,熱補丁程式碼錨點已定位
- [x] 使用者決策已取得(合併單一入口;三張一起處理)
- [x] 既有測試模式(Fake client、stub 斷言)已確認
