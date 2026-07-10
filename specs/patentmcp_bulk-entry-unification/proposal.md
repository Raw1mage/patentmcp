# Proposal: patentmcp_bulk-entry-unification

## Why

- 2026-07-10 兩張 BR 揭露:EPO 建池全撈熱補丁(`epo_bulk_harvest` per-page absorb、`_keyword_to_cql` 布林轉譯)已實戰生效但**未正式化**——無契約文件、無測試、KB 來源梯未收錄。
- 同時 bulk 工具面已碎裂成三個語義重疊的入口:`patent_bulk_export`(GPSS 分類軸)、`patent_bulk_harvest`(GPSS keyword-aware)、`epo_bulk_harvest`(EPO 收割)。換執行者要靠試錯才知道選哪個。
- 使用者決策(2026-07-10):**合併成單一 bulk 入口,依 source 參數路由**,而非分立三工具各補文件。

## Original Requirement Wording (Baseline)

- 「處理新開的BR」+ question 決策:「合併成單一 bulk 入口」「三張一起處理」(含 BR_20260628 驗證 B)。

## Requirement Revision History

- 2026-07-10: initial draft created via plan-init.ts

## Effective Requirement Description

1. 新增單一 MCP 工具 `patent_bulk`,以 `source: "gpss"|"epo"` 顯式路由;GPSS 分支依 keyword 有無內部走分類軸(export)或 keyword 收割(harvest)路徑;EPO 分支走 per-page absorb 收割。
2. 三個舊 bulk 工具轉 `TOOL_RENAMED` stub(`use: "patent_bulk"`),沿 BR_20260706 一個 release cycle 的下架模式。
3. 測試固化:`_keyword_to_cql` 布林/片語/括號/NOT 四類、`patent_bulk` 路由、EPO per-page absorb 冪等 + `next_skip` 斷點續撈。
4. KB/skill 來源梯同步:`patent_bulk` 契約收錄、EPO 分支支援布林 keyword 能力補註。
5. BR_20260628 驗證 B:delegation-clauses runtime 注入端到端驗證(過則三段全綠可 close)。
6. (2026-07-10 使用者擴充,revise)EPO 自動 date 切片:`patent_bulk(source="epo")` 母數 > skip wall(2000)時自動遞迴二分 date 切片至每片 < 2000,逐片收割;回傳 slice_plan(每片 total)+ 總和守恆自證;切片未生效 fail-fast(收搜 issue_20260710_epo_bulk_auto_date_slicing)。

## Scope

### IN
- `src/patent_mcp_server/search_dispatcher.py` 統一 bulk 路由 + envelope 對齊(GPSS 側補 `next_skip`/`exhausted`)
- `src/patent_mcp_server/patents.py` 新工具 `patent_bulk` + 三舊工具 stub 化
- `tests/` 新測試檔(unified bulk 路由、`_keyword_to_cql`、EPO 冪等/續撈)
- `skills/patentworks/SKILL.md` §5 來源梯條目更新
- 三張 BR 歸檔(issues/ → issues/closed/)

### OUT
- EPO 15/min 節流自適應 backoff(仍 OUT:切片已把單呼叫規模控在 wall 內,節流靠既有 per-page 節奏;真撞 429 再另案)
- bulk 路徑任何爬蟲整合(天條:bulk 永遠官方 only)
- GPSS 側 per-page absorb 重構(GPSS 書目隨頁內建、無 fan-out 逾時風險,維持現行收尾吸收)

## Non-Goals

- 不改 `patent_search` 來源梯行為(EPO 布林修復已在 `_run_epo` 生效,本案只補測試)
- 不做跨源自動 fallback(GPSS miss 不自動改打 EPO——顯式 fail-fast,使用者天條)

## Constraints

- 舊工具下架必須走 TOOL_RENAMED stub,不得直接刪除(舊 skill 投影/playbook 需 typed 修正)
- COALESCE upsert 冪等契約不得破壞(重跑不覆寫已有完整欄位)
- EPO OPS skip wall(~2000)與 15/min 節流為外部硬限制

## What Changes

- MCP 工具面:+1(`patent_bulk`)、-3(轉 stub)
- dispatcher:新增 `bulk()` 統一路由函式,復用既有 `bulk_export`/`bulk_harvest`/`epo_bulk_harvest` 實作
- 測試:+2 檔(unified bulk、keyword_to_cql/續撈)

## Capabilities

### New Capabilities
- `patent_bulk`: 單一窮盡批次入口,source 顯式路由,統一 envelope(含 `next_skip`/`exhausted` 續撈語義)

### Modified Capabilities
- `patent_bulk_export` / `patent_bulk_harvest` / `epo_bulk_harvest`: 降級為 TOOL_RENAMED 轉址 stub

## Impact

- 受影響:patentworks SKILL.md §5、既有 bulk 測試、任何引用舊 bulk 工具的 flow 文件
- BR_20260628 驗證 B 屬跨 repo 驗證(opencode runtime 注入),不改 patentmcp 程式
