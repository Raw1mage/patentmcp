# Handoff: patentmcp_classification-bulk-export

## Execution Contract

- 交付「分類軸批次匯出」能力:純分類軸(ipc/cpc/uspc)+ 大 expQty + 自動分頁的窮盡批次匯出,強制全欄(DD-3),官方 miss 即真 0 絕不退爬蟲(DD-5),落地對接 `patentdb_import_csv`(DD-6)。
- **Done 定義**:`patent_bulk(source="gpss", <axis>, keyword=None)` 走 GPSS 官方端點自動分頁拉至 num 或軸窮盡,回 `{success, records[], source:"gpss", provenance[], total, patentdb_absorb}`;records 已入 patentdb;無 keyword AND 收窄;GPSS miss → `success=True` + `records=[]` 且**無** `error_code` / 不觸 SCRAPING_REQUIRED / 不呼叫 gpatents。
- **不回退**:不下架 `patent_search`,不改 patentdb schema,不動單號取文/取圖工具。

## Required Reads

- `plans/patentmcp_classification-bulk-export/{proposal,design,tasks}.md` — DD-1..7 決策脈絡。
- `src/patent_mcp_server/search_dispatcher.py` — `bulk_export` / `_bulk_pull_gpss`(核心分頁匯出邏輯,line 336/405);`_entry`(provenance,line 229);`_envelope`(line 1399)。
- `src/patent_mcp_server/patents.py` — `patent_bulk` 統一前端入口(line 4112);retired `patent_bulk_export`/`patent_bulk_harvest`/`epo_bulk_harvest` → TOOL_RENAMED redirect(line 4320+)。
- `src/patent_mcp_server/gpss/client.py` — `search(num,skip,fields,fmt)`:expQty=num / expSkip=skip / expFld=fields。
- `src/patent_mcp_server/patentdb_store.py` — `import_records`(line 450 inline 旁路)/ `put()` COALESCE-only upsert(line 238)。
- `tests/test_classification_bulk_export.py` — monkeypatch-GPSS 測試範式(不打真網路)。

## Stop Gates In Force

- **DD-1 使用者裁決(2026-07-07)**:批次匯出入口 = 獨立工具 + 內部共用函式(兩者都要)。已裁決,無需再問。
- **DD-5 no-fallback 天條**:批次路徑**不接來源梯尾級**;GPSS miss 即真 0。改動此行為前須人工核准。
- **graduate 閘**:`verified → living`(`plan_graduate`)為**使用者專屬**閘;AI 僅回報 readiness,`lifecycle.ts` 需 `--user-approved` flag。

## Execution-Ready Checklist

- [x] DD-1 已由使用者裁決(獨立工具 + 內部共用),無待決前置。
- [x] `GPSS_USER_CODE` 已於容器/cfg 層設定(否則 `patent_bulk(source="gpss")` 回 `GPSS_NOT_CONFIGURED` fail-fast)。
- [x] `patentdb_import_csv` / `import_records` 既有且 `put()` COALESCE-only(半殘 row 回補不破壞既有欄位),無 schema 變更。
- [x] 測試以 monkeypatch GPSS client,**不打真網路**,不吃 TIPO 配額。
