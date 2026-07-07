# Design: patentmcp_classification-bulk-export

## Context

patentmcp 現況(已讀原始碼核實):

- **檢索入口收斂為單一 `patent_search`**(plan `patentmcp_search-dispatcher`,verified 2026-07-03)。語義是 relevance search:查詢軸疊 AND、`num` 預設 30(`patents.py` line 2670)、來源梯 GPSS→EPO→PPUBS→gpatents,官方全 miss 且無 `allow_scraping=True` 即回 `SCRAPING_REQUIRED`。
- **GPSS client**(`gpss/client.py`)`search(num=30)` 直接把 `num` 寫成 `expQty`(`_build_query`),GPSS 對 expQty 無小上限;`expSkip` 分頁參數已支援(`if skip:`);`DEFAULT_FIELDS="PN,ID,TI,IN,PA,AB,CS,CL"` 齊全;`expFmt` 僅 json/xml。
- **patentdb**(plan `patentdb_unified-database`,verified):`patentdb_import_csv` 批次入庫、`put()` COALESCE-only 漸進 upsert(`patentdb_store.py` line 238)、`import_records()` inline 旁路(line 450)。EPO biblio 二段式旁路不回英文標題 → 306 件 `title_en` 空白半殘 row。

需要現在做的原因:分類軸全景窮盡取數是實務高頻需求(AIOT 全景擴充),但被 relevance search 語義閹割(keyword AND 收窄 → 官方 0 命中 → 退爬蟲),且半殘 row 持續污染 patentdb。GPSS 端點原生支援批次匯出,只差一個對的語義入口。

## Goals / Non-Goals

**Goals**

- 提供純分類軸 + 大 expQty + 自動分頁的窮盡批次匯出能力,落地完整書目(強制全欄 expFld)。
- 官方 miss 即真 0,**絕不退爬蟲**(no-fallback 天條)。
- 對接既有 `patentdb_import_csv`,patentdb 只進完整 row。
- 不回退 `patentmcp_search-dispatcher` 的任何 conformance 面(單一相關性檢索入口保留)。

**Non-Goals**

- 不做 EPO/PPUBS 批次匯出(聚焦 GPSS 原生 expQty)。
- 不重做 patentdb schema。
- 不自主全庫爬取。

## Decisions

- **DD-1(已裁決 2026-07-07:兩者都要):批次匯出入口 = 獨立工具 + 內部共用。**
  - **裁決**:實作獨立工具 `@mcp.tool() patent_bulk_export` 為**主前端入口**(語義隔離,AI 路由不含糊,對應 search-dispatcher「工具層才是硬約束」);同時把「分類軸批次分頁匯出」核心邏輯抽為 **GPSS client / dispatcher 層的內部共用函式**,讓 `patent_search` 內部也能複用(例如 relevance 路徑需要窮盡某軸時)。
  - **形狀**:前端 = 兩個並列 MCP 工具(relevance `patent_search` + bulk `patent_bulk_export`,29→30);後端 = 單一共用批次分頁實作,兩入口都接。避免邏輯雙份。
  - **不採**:單純 `patent_search(mode=)` 旗標(同簽名分岔兩語義易混淆);也不採「只做獨立工具、邏輯不共用」(會與 patent_search 潛在的窮盡需求重複造輪子)。

- **DD-2:GPSS `search()` 分頁迴圈化。** `num` 超過單頁上限時,以 `expSkip` 為游標自動翻頁,累積 records 至 `num` 或某頁回空(表示軸已窮盡)為止。單頁 expQty 取合理值(如 200/500,依 GPSS 實測穩定值)。保留既有 `search()` 單頁行為給 relevance 路徑,分頁迴圈為批次路徑專用或以參數開關。

- **DD-3:批次路徑強制 `expFld=DEFAULT_FIELDS`(全欄)。** 不允許呼叫端縮欄,杜絕半殘 row(這是 BR「半殘 row」根因的正面對策)。

- **DD-4:批次路徑純分類軸,keyword 不作 AND 收窄。** 主軸為 `ipc`/`cpc`/`uspc`(至少一個必填);keyword 若給,作 OR 加權或忽略(design 傾向:批次匯出忽略 keyword 收窄,只用分類軸——避免任何過度收窄)。

- **DD-5:官方 miss 不退爬蟲。** 批次路徑不接來源梯尾級;GPSS 未 configured → 明確錯誤;GPSS 回 0 → 真 0(`provenance` 標 miss reason=zero_hits),不 fallback。對齊 no-fallback 天條。

- **DD-6:落地走既有正規化 → CSV → import_csv。** 沿用 `screening_table.py` / records 正規化欄位,輸出 records(或直接寫 CSV),交 `patentdb_import_csv` 吸收;patentdb `put()` COALESCE-only 保證半殘 row 回補不破壞既有欄位。無 schema 變更。

- **DD-7:標準面同步。** 破壞性?否——新增能力,不下架既有工具。`mcp.json` version:新增工具屬 feature add,minor bump(0.3.x → 0.4.0 或 patch,依 fleet 慣例)。instructions 補宣告「relevance search(`patent_search`)vs 分類軸批次匯出」兩種語義分工。

## Risks / Trade-offs

- **TIPO 每日配額**:大 expQty × 自動分頁可能一次吃掉大量配額 — mitigation:num 設合理硬上限(如 5000),分頁間可選延遲,呼叫端明確指定量。
- **GPSS 單頁 expQty 穩定上限未知** — mitigation:實測取穩定值(200/500),分頁補足;不假設可一次 expQty=5000。
- **選項 A 增加工具數牴觸 search-dispatcher 的「收斂」哲學** — mitigation:兩者語義正交(relevance vs bulk),不是同類工具重複;文件明確分工。
- **keyword 完全忽略可能漏掉軸內細分需求** — mitigation:批次匯出定位是「拉整軸」,細分交後續 relevance search / screening,不在批次階段收窄。

## Architecture (hung on the IDEF0 skeleton)

本案架構直接從 idef0.json 的 A0 分解導出(IDEF0-first):

- **A1 組裝純分類軸查詢** — 落在 `gpss/client.py` 的 condition 組裝 + `patent_bulk_export` 入口簽名(patents.py)。DD-3(強制 expFld 全欄)/ DD-4(純分類軸、keyword 不收窄)在此落地。
- **A2 分頁窮盡拉取** — 落在 `gpss/client.py` `search()` 的 expSkip 自動分頁迴圈(DD-2),為兩入口共用的內部函式(DD-1)。DD-5(miss 不退爬蟲)在此落地。grafcet.json step2–4 就是 A2 的 runtime 迴圈。
- **A3 正規化落地** — records 正規化(沿用 screening_table 欄位)→ CSV → `patentdb_import_csv`(DD-6)。patentdb `put()` COALESCE-only 保證半殘 row 回補不破壞。

## Critical Files

- `src/patent_mcp_server/gpss/client.py` — `search()` / `_build_query`,expQty/expSkip/expFld/分頁迴圈的實作點。
- `src/patent_mcp_server/patents.py` — 新工具註冊(或 patent_search mode 分岔);patent_search 簽名 line 2658。
- `src/patent_mcp_server/patentdb_store.py` — `import_records` line 450 / `put` COALESCE line 238,確認相容(預期無需改)。
- `mcp.json` — version bump + instructions 兩語義分工。
- `skills/patentworks/SKILL.md` §5 / `flows/priorsearch.md` — 工具清單與 flow 同步。
- `tests/test_br20260628_tooling_gaps.py`(pattern 參考)— monkeypatch-client 測試範式。
