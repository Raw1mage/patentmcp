# Design: patentmcp_search-dispatcher

## Context

patentmcp 的 MCP 表面暴露 4 個並列檢索工具:`gpss_search`(TIPO 官方,首選)、
`epo_search`(EPO OPS CQL)、`uspto_patents`(PPUBS method-dispatcher)、
`gpatents_search`(patents.google.com 爬蟲,最後手段)。所有工具在
`patents.py` 的單一 `FastMCP("patentmcp")` 實例上無條件註冊(patents.py:25),
credential 缺失是呼叫時報錯,不影響工具可見性。

問題:**來源優先序目前只存在於 skill 文件(SKILL.md §5 來源梯),是 AI 自律
約束**。冷 context 的 agent / 子代理面對 4 個同義工具時,永遠先抓語義最直觀
的 `gpatents_search`——爬蟲被限速封鎖、非官方、且違反 flow 禁令。文件層擋不
住,必須把來源選擇收進工具層:單一 `patent_search` dispatcher,server 端依
來源梯自動選路。

重構基準:fleet MCP integration standard
(`opencode/specs/mcp-integration-standard/standard.md`)。patentmcp 已
fully-conformant(gap matrix §12);本案的標準面義務:R4.1 命名、R8.1 live
registry 自動反映下架、R3/R13.5 instructions 重寫、R5.1 version bump、
fail-fast no-fallback 天條。

## Goals / Non-Goals

**Goals**

- MCP 檢索表面收斂為單一 `patent_search`;AI 無從自選來源。
- Server 端來源梯:GPSS → EPO → PPUBS → (gated) gpatents,每級嘗試結果落 `provenance`。
- 爬蟲尾級硬閘:`allow_scraping=False` 預設,全官方梯 miss 時回 `SCRAPING_REQUIRED` 結構化錯誤。
- `build_screening_table` 內部改接 dispatcher,獲得三級官方梯。
- 標準面同步:mcp.json version/instructions、README、skill 文件。

**Non-Goals**

- 不做多來源結果聚合排序、不做並行 fan-out(節流合規優先)。
- 不動單號取文/取圖工具、不動 client 層、不動 transport/lifecycle/health。
- 不復活 BigQuery 檢索。

## Decisions

- DD-1: **下架而非改名/並存**——舊 4 檢索工具移除 `@mcp.tool()` 裝飾器,函式本體降為模組內部函式(`_gpss_search_impl` 等)。理由:並存 = AI 仍可繞過 dispatcher;R8.1 live registry 讓下架零維護。(使用者 question() 裁決)
- DD-2: **gpatents 留為 allow_scraping 閘道尾級**,沿用 `fetch_patent_pdf` 的既有 gate 模式(patents.py:2652 `SCRAPING_REQUIRED` + `provenance.scraping` 標記)。(使用者 question() 裁決)
- DD-3: **路由以「configured() + 查詢軸能力」雙條件選路**,不做 per-call 健康探測。GPSS 全軸支援為預設主力;USPC(`CCL/`)軸直達 PPUBS(GPSS 無此軸);EPO 為 GPSS 不可用時的官方次選。軸能力矩陣以偵查結論固化為 `AXIS_CAPABILITY` 常數表。
- DD-4: **EPO 走 search→biblio 二段**補書目(`epo_search` 只回 pub numbers,epo/client.py:250);二段上限受 EPO 節流(15/min)保護,`num` 大時 provenance 記 `biblio_truncated`。
- DD-5: **統一回傳 envelope**:`{success, records[], source, provenance[], gaps[], total}`;records 用 screening_table.py 既有 record schema(誠實留白,不造假)。provenance 每級一筆:`{source, status: hit|miss|skipped|error, reason, elapsed_ms}`。
- DD-6: **`uspto_patents` 不整支下架**,只移除 search 類 method(`ppubs_search_patents` / `ppubs_search_applications`);取文類 method(full document、app data…)保留——它們是取文工具,不在檢索收斂範圍。method 白名單在 tool docstring 與 dispatch 表同步縮減。
- DD-7: **`pub_number` 軸直通**:單號查詢(三地通用)仍由 dispatcher 承接(GPSS `PN` 條件),取代舊 `gpss_search(pub_number=...)` 用法,skill 文件同步改寫。
- DD-8: **version 0.2.3 → 0.3.0**:0.x 期以 minor 位承載 breaking(工具下架);mcp.json instructions 重寫為「檢索一律 patent_search,來源梯內建」。

## Risks / Trade-offs

- **舊工具名散佈於 skill 文件與歷史 event** — mitigation: skill 文件全面同步(tasks 內列清單);README 加遷移對照表(舊工具 → dispatcher 參數寫法)。
- **EPO biblio 二段放大延遲**(15/min 節流,30 筆 ≈ 2 分鐘)— mitigation: EPO 級預設只在 GPSS 不可用時觸發;`num` 上限文件化;provenance 註記截斷。
- **`build_screening_table` 行為變化**(原 GPSS→gpatents 二源,改三級官方梯)— mitigation: gpatents 級在 screening 路徑同樣受 allow_scraping 閘,預設不再靜默走爬蟲——這是行為修正,不是回歸;測試固化。
- **內部呼叫點斷裂風險**(`patent_get_claim1` 等引用既有函式)— mitigation: 只動裝飾器不動函式簽名;grep 全倉引用點逐一驗證;測試跑全套。

## Critical Files

- `src/patent_mcp_server/patents.py` — MCP 表面:新增 `patent_search`、移除 4 個檢索裝飾器、`uspto_patents` method 縮減。
- `src/patent_mcp_server/search_dispatcher.py`(新)— QuerySpec 正規化、AXIS_CAPABILITY 矩陣、來源梯路由、provenance 組裝。
- `src/patent_mcp_server/screening_table.py` — `ppubs_to_records`(新)、EPO biblio 映射(新);record schema 是統一回傳的真相源。
- `src/patent_mcp_server/gpss/client.py`、`epo/client.py`、`gpatents/client.py`、`uspto/`(ppubs client)— **不動**,dispatcher 只消費其現有介面。
- `mcp.json` — version 0.3.0 + instructions 重寫(R3/R5.1/R13.5)。
- `skills/patentworks/SKILL.md`、`flows/screening.md`、`flows/priorsearch.md`、`skills/patent-practitioner-workflow.md` — 來源梯敘述改為 dispatcher 內建行為。
- `tests/test_search_dispatcher.py`(新)— monkeypatch-client 路由測試。
