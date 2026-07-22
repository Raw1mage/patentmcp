# Proposal: patentmcp_classification-bulk-export

## Why

`patent_search` 是 **相關性檢索**(relevance search)語義:多個查詢軸疊 **AND 收窄**、`num` 預設 30、官方來源全 miss 就退爬蟲尾級。這套語義做不到另一種需求——**純分類軸 + 大 expQty 窮盡批次匯出**:把某個 IPC/CPC/USPC 分類軸底下的完整書目一次批次拉下、轉 CSV、入 patentdb。

而 GPSS 端點本身**原生支援**這種批次匯出(已讀 `gpss/client.py` 核實):

- `expQty`(一次回幾筆)由 `num` 控制、直寫 query,**GPSS 對 expQty 無小上限**——這是 TIPO「一次匯出大量」的原生能力。
- `expSkip` 分頁參數 `_build_query` 已支援(`if skip:`),可自動翻頁拉完整軸。
- `expFld` 預設 `PN,ID,TI,IN,PA,AB,CS,CL`——欄位齊全含標題(TI)/申請人(PA)/摘要(AB)/CPC(CS)/claims(CL)。

缺的不是端點能力,而是**一支把這能力以「分類軸批次匯出」語義暴露出來的工具**。

具體後果(BR_20260707 實測):`patent_search(ipc="G16H40/67", keyword="独居 老人 监测", databases=["CN"], num=50)` → `gpss miss(zero_hits) → epo parse error → ppubs skipped → SCRAPING_REQUIRED`。keyword 被當 AND 收窄疊在 IPC 上導致過度收窄、官方 0 命中、退爬蟲。而且走 EPO biblio 二段式旁路吸收進 patentdb 的是**半殘 row**——今日 306 件 `title_en` 空白(EPO biblio 不回英文標題)。

## Original Requirement Wording (Baseline)

- 「需把某 IPC 分類軸的完整書目一次批次拉下轉 CSV,但現有工具做不到,只能逐條檢索、且塞進 patentdb 的是缺英文標題的半殘 row。」(BR_20260707,回報情境:智慧家庭異常偵測 AIOT 全景擴充)
- 「工具層修,不徒手繞道」——新增一支「分類軸批次匯出」工具(或給 `patent_search` 一個 `mode="bulk_export"` 旗標)。

## Requirement Revision History

- 2026-07-07: 初始草稿(BR_20260707 治本;根因已讀 `gpss/client.py` / `patents.py` 核實)。

## Effective Requirement Description

新增一條「**分類軸批次匯出**」能力,語義與 `patent_search` 的相關性檢索明確區隔:

1. **純分類軸**(`ipc` / `cpc` / `uspc`)為主軸,**不強制疊 keyword AND**。keyword 若給,僅作 OR 加權/選填,**不作收窄**——避免過度收窄導致官方 0 命中。
2. **大 `expQty`**:允許 `num` 到數千(對齊 TIPO 每日配額),透過 `expSkip` **自動分頁翻頁**拉完整軸,而非單頁 30 筆。
3. **強制 `expFld=PN,ID,TI,IN,PA,AB,CS,CL`**(欄位齊全),杜絕半殘 row。
4. **官方 miss 不退爬蟲**:批次匯出是官方 GPSS 能力,miss 就是真 0(該分類軸下真的沒有),不該 fallback 到爬蟲尾級。
5. **落地為完整書目 records**(或直接 CSV),供既有 `patentdb_import_csv` 吸收 → patentdb 只進**完整 row**。
6. **附帶回補**:今日 306 件 `title_en` 空白的半殘 row,因 `patentdb_store.put()` 是 COALESCE-only(非空不覆寫),可用本工具重抓對應軸 `import_csv` 覆蓋補齊,不破壞既有欄位。

## Scope

### IN

- 新增分類軸批次匯出能力(工具形式:獨立工具 vs `patent_search(mode="bulk_export")` 旗標——由 design DD 裁決)。
- GPSS client 層:`num` 上限放寬 + `expSkip` 自動分頁迴圈(拉完整軸至 expQty 或無更多結果)。
- 強制 `expFld` 全欄 + 純分類軸語義(keyword 不作 AND 收窄)。
- 官方 miss → 真 0 回傳(**不退爬蟲**),明確 `provenance`。
- 落地 records / CSV,對接既有 `patentdb_import_csv`。
- `mcp.json` instructions / README / patentworks skill 文件同步(宣告兩種檢索語義的分工)。
- 單元測試(monkeypatch GPSS client,不打真網路):分頁迴圈、expFld 強制、miss-不退爬蟲、大 num。

### OUT

- 廢除 `patent_search`(相關性檢索保留;本案是**並列新增**批次匯出語義)。
- 改變 `candidates.csv` 欄位格式(沿用既有格式,`import_csv` 直接吃)。
- 改動單號取文/取圖工具(`gpatents_get` / `fetch_patent_pdf` / `epo_family` 等)。
- 線上同步 / 雲端 DB。
- EPO / PPUBS 端的批次匯出(本案聚焦 GPSS 原生 expQty 能力;EPO biblio 半殘正是動機,不在其上疊批次)。

## Non-Goals

- 不追求「自動全景蒐集」——工具只在被呼叫時拉指定分類軸,不自主爬全庫。
- 不把批次匯出做成會退爬蟲的東西——官方能力範圍內,miss 即真 0。
- 不重做 patentdb schema(沿用既有 patents / patents_fts / screenings 三表 + COALESCE upsert)。

## Constraints

- 只用 GPSS 原生 API 能力(`expQty` / `expSkip` / `expFld`),不自造爬蟲/查詢輪子。
- `expFmt` 只有 json/xml——CSV 需 API 層自 JSON 轉(沿用既有 records 正規化 → `import_csv`)。
- 受 TIPO 每日配額約束:大 expQty 需分頁 + 合理上限,不無限拉。
- `GPSS_USER_CODE` 需已設(容器/cfg 層)。

## What Changes

- 新增分類軸批次匯出入口(工具或旗標)。
- GPSS client `search()` 分頁迴圈化 + num 上限放寬。
- patentdb 半殘 row 回補走既有 COALESCE upsert,無 schema 變更。

## Capabilities

### New Capabilities

- **分類軸批次匯出**:純分類軸 + 大 expQty + 自動分頁 + 強制全欄 + miss 不退爬蟲 → 完整書目落地。

### Modified Capabilities

- **GPSS client `search()`**:從單頁升級為可自動分頁拉完整軸;`num` 語義從「回幾筆」擴為「拉到幾筆(跨頁)」。
- **patentdb 吸收**:批次匯出路徑保證完整 row(強制 expFld),對比既有 EPO biblio 旁路的半殘 row。

## Impact

- `src/patent_mcp_server/gpss/client.py`(expQty/expSkip/expFld/分頁迴圈)
- `src/patent_mcp_server/patents.py`(新工具或 patent_search mode 旗標;patent_search 簽名 line 2658)
- `src/patent_mcp_server/patentdb_store.py`(import_records / put COALESCE line 238/450——確認相容,無需改)
- `mcp.json`(instructions 宣告兩種檢索語義)、README、`skills/patentworks/SKILL.md`(§5 / priorsearch flow)
- patentdb 既有 306 件 `title_en` 空白半殘 row(回補,非破壞)
