# Proposal: patentmcp_search-dispatcher

## Why

patentmcp 目前暴露 4 個分散的檢索工具(`gpss_search` / `epo_search` /
`gpatents_search` / `uspto_patents` 的 ppubs_search 路徑)。實務觀察:**AI 面對
多個同類工具時路由不受控**——`gpatents_search`(網頁爬蟲、非官方、易被封鎖)
語義最直觀,AI 永遠先抓它,skill 文件寫再多「GPSS 首選」也擋不住冷 context
的子代理。工具層才是硬約束:**把來源選擇從 AI 手上收走,做成 server 端
dispatcher**,前端只留一個 `patent_search`,後端依來源梯(GPSS→EPO→PPUBS)
與查詢軸自動分配 endpoint,爬蟲只留 `allow_scraping=True` 授權尾級。

重構基準採用 fleet MCP integration standard
(`opencode/specs/mcp-integration-standard/standard.md`),patentmcp 已是
fully-conformant(R7/R8 landed via `patentmcp_mcp-standard-conformance`),
本案不得回退任何 conformance 面,並補強下列條款的落實:

- **R4.1** 新工具自帶前綴:`patent_search` 以 registry 名 `patentmcp_patent_search` 呈現(FastMCP 單一實例現況即符合)。
- **R8.1** `/tools` 取自 live registry——下架舊工具 = 移除裝飾器即自動反映,無需另行維護清單。
- **R3/R13.5** `mcp.json.instructions` 必須同步改寫:宣告單一檢索入口與來源梯語義,AI 無需(也無從)自選來源。
- **R5.1** 破壞性變更(工具下架)→ `mcp.json` version bump(0.2.3 → 0.3.0;0.x 期以 minor 當 breaking 位)。
- **fail-fast / no-fallback 天條**:來源梯每級失敗記錄於 `provenance`,全 miss 回結構化錯誤,不靜默降級到爬蟲。

## Original Requirement Wording (Baseline)

- 「我覺得search tool應該集中成一個單一前端dispatcher,後端再去分配不同endpoint,不然AI永遠先用gpatent,完全不受控」
- 「既然要重構,也順便讀取mcp integration standard做為重構基準。」
- question() 裁決:舊分散檢索工具**全部下架,只留 dispatcher**;gpatents 檢索**留為 allow_scraping 閘道尾級**。

## Requirement Revision History

- 2026-07-03: initial draft(偵查完成:29 tools、註冊機制、查詢軸對照、configured() 偵測、正規化 adapter 現況)

## Effective Requirement Description

1. **新增 `patent_search` 統一檢索工具**(單一 MCP 檢索入口):
   - 統一查詢參數:`cpc` / `ipc` / `keyword`(+`keyword_field`)/ `applicant` / `inventor_country` / `pub_number` / `date_from` / `date_to` / `countries`(或 databases)/ `num` / `skip`,外加 `allow_scraping: bool = False`。
   - Server 端路由(來源梯,依 configured() 與查詢軸能力選路):
     - **① GPSS**(`gpss_client.configured()` 為真)——預設主力,全軸支援,涵蓋 US/CN/TW。
     - **② EPO OPS**(`epo_client.configured()` 為真)——GPSS 不可用或需 EPO 專屬軸(CQL 級布林)時;search 只回 pub numbers,需 biblio 二段補書目。
     - **③ USPTO PPUBS**——US-only 軸(USPC `CCL/` 語法)或 GPSS/EPO 皆 miss 的 US 案。
     - **④ gpatents 爬蟲尾級**——僅當 ①②③ 全 miss **且** `allow_scraping=True`;預設回 `{error_code:"SCRAPING_REQUIRED"}`(沿用 `fetch_patent_pdf` 既有 gate 模式)。
   - 回傳統一 record schema(沿用 screening_table.py 的正規化欄位)+ `source` + `provenance`(各級嘗試結果:attempted/skipped/hit/miss+原因)。
2. **下架 4 個分散檢索工具**:移除 `gpss_search`、`epo_search`、`gpatents_search` 的 `@mcp.tool()`,`uspto_patents` 移除 search 類 method(保留取文類:full document / batch claims)。函式本體降為內部函式供 dispatcher 與既有呼叫點(`build_screening_table`、`patent_get_claim1` 等)使用。
3. **單號取文工具不動**:`google_get_patent*`、`ppubs_batch_get_claims`、`epo_family`/`epo_biblio`、`fetch_patent_pdf`、`extract_representative_figure`、`gpss_download_*`、`gpatents_get`/`gpatents_download_*`(單件降級用)等取文/取圖工具維持現狀——本案只收斂「檢索」面。
4. **`build_screening_table` 改吃 dispatcher**:內部改呼叫統一檢索路徑,自然獲得 EPO/PPUBS 梯級(現況只有 GPSS→gpatents 二源)。
5. **正規化 adapter 補齊**:新增 `ppubs_to_records`;EPO 走 search→biblio 二段後以 biblio 欄位映射 record schema。
6. **標準面同步**:`mcp.json`(version bump、instructions 重寫宣告單一檢索入口)、README、skill 文件(SKILL.md §5 來源梯改寫為「dispatcher 內建」、screening/priorsearch flow 更新工具名)。
7. **測試**:沿用 `tests/test_br20260628_tooling_gaps.py` 的 monkeypatch-client 模式,覆蓋:GPSS 首選路由、GPSS 未 configured 時 EPO/PPUBS 降級、USPC 軸直達 PPUBS、SCRAPING_REQUIRED gate、provenance 完整性、`build_screening_table` 走新路徑。

## Scope

### IN

- 新 `patent_search` dispatcher tool(patents.py)+ 路由/正規化模組。
- 下架 4 個檢索工具的 MCP 裝飾器(本體轉內部)。
- `build_screening_table` 內部改接 dispatcher。
- `ppubs_to_records` / EPO 二段正規化。
- `mcp.json`(version、instructions)、README、skills 文件同步。
- 單元測試(monkeypatch clients,不打真網路)。

### OUT

- 單號取文/取圖工具(`*_get*`、`fetch_patent_pdf`、`ppubs_batch_get_claims`…)的介面變更。
- `search_audit` / matrix-log schema 變更(其紀錄格式可為 dispatcher provenance 參考,但不在本案改)。
- BigQuery 檢索復活(已永久下架,不回頭)。
- transport / lifecycle / health 等已 conformant 的標準面(R1/R2/R7/R8 不動)。
- opencode host 側任何改動。

## Non-Goals

- 不做語義排序聚合(不合併多來源結果重排;一次呼叫走一條梯級,provenance 說明為何)。
- 不做每來源並行 fan-out(合規節流優先;單線順序梯級)。

## Constraints

- **No fallback 天條**:梯級降級必須顯式記錄於 provenance 並可稽核;爬蟲尾級必須 `allow_scraping=True` 明示授權,預設 fail-fast 回 `SCRAPING_REQUIRED`。
- **Back-compat 例外聲明**:本案是刻意的 breaking change(下架工具),透過 version bump + instructions 重寫聲明;`/tools` live registry 自動反映(R8.1),無殘影。
- **既有內部呼叫點不斷**:`build_screening_table`、`patent_get_claim1`、`fetch_patent_pdf` 等引用的 client 層(gpss_client/epo_client/ppubs_client/gpatents client)完全不動,只動 MCP 表面。
- **節流照舊**:EPO 15/min、GPSS 單線 + sleep、gpatents SoftScrapePolicy 均沿用 client 層現有機制。

## What Changes

- `src/patent_mcp_server/patents.py` — 新增 `patent_search` tool;移除 4 個檢索 `@mcp.tool()` 裝飾器;`uspto_patents` method 白名單縮減。
- `src/patent_mcp_server/search_dispatcher.py`(新)— 路由邏輯 + provenance 組裝。
- `src/patent_mcp_server/screening_table.py` — 新增 `ppubs_to_records`、EPO biblio 映射。
- `mcp.json` — version 0.3.0、instructions 重寫。
- `skills/patentworks/SKILL.md` §5、`flows/screening.md`、`flows/priorsearch.md`、`skills/patent-practitioner-workflow.md` — 工具名與來源梯敘述同步。
- `tests/test_search_dispatcher.py`(新)。

## Capabilities

### New Capabilities

- 單一 `patent_search` 檢索入口,server 端來源梯路由 + provenance 稽核。

### Modified Capabilities

- `build_screening_table` 獲得三級官方梯(GPSS→EPO→PPUBS)。
- MCP 檢索表面由 4 工具收斂為 1。

## Impact

- AI agent:無從再「先用 gpatents」——檢索只有一個工具,爬蟲只能透過授權參數觸及。
- Skill 文件:來源梯從「AI 自律遵守」降為「工具內建行為說明」,大幅簡化。
- 外部消費者(若有直呼舊工具者):breaking,由 version bump 與 README 遷移說明承接。
