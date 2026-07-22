# Design: br20260628_tooling_skill_gpss_gaps

## Context

三份 BR 的可修點落在三個 surface:
- **patentmcp 工具層** (`src/patent_mcp_server/patents.py`):~2900 行,工具用 `@mcp.tool()` 裝飾。
- **GPSS 解析層** (`gpss/client.py` + `screening_table.py`):search 與 records 映射。
- **patentworks skill** (`skills/patentworks/SKILL.md` §5):來源優先序 + 爬蟲天條。

## Goals / Non-Goals

- Goal:移除「靜默走爬蟲」的隱性行為,改為顯式 gate;補齊 claim1 缺失旗標;更新 skill 心智模型。
- Non-Goal:不重寫 GPSS headless 機制;不碰 BigQuery 預算策略;不處理 opencode 端工具 surface。

## Decisions

- **DD-1**: `fetch_patent_pdf` 加 `allow_scraping: bool = False`。預設 False 時,`gpss_pdf`(`provenance.scraping:true`)這條來源被跳過並在 attempts 留 `SKIPPED_SCRAPING_NOT_AUTHORIZED`;全部官方來源 miss 後回 `error: "SCRAPING_REQUIRED"` 提示需授權。**這是移除靜默 fallback、改為顯式 decision gate,符合天條 §11(不偷加 fallback、fail fast)**。`extract_representative_figure` / `patentmcp_batch_download_figures` 等下游呼叫端需傳 `allow_scraping=True`(它們本就是爬蟲工具,語義一致)。
- **DD-2**: 參數命名統一 `publication_number`(單)/ `publication_numbers`(複)。舊名 `patent_number` / `patent_numbers` 透過函式內 alias 解析(`pub = publication_number or patent_number`)保留向後相容,不破壞既有呼叫端;描述標註 canonical 名。
- **DD-3**: `extract_representative_figure` 失敗分級:`_locate_figure_page` 回 None 時,再探測 PDF 的 image XObject 數;>0 → 回 `NO_FIGURE_PAGE_BUT_IMAGES_PRESENT`(success=False,但帶 `image_count` + `pages` + 建議「人工挑選或從 PDF 抽圖」);=0 → 維持 `NO_FIGURE_PAGE`。不臆測哪張是代表圖(避免再次插錯頁)。
- **DD-4**: `ppubs_get_full_document` 加 `publication_number` 便利路徑。dispatcher 在 method=ppubs_get_full_document 且未給 guid/source_type 但給了 publication_number 時,內部走 `ppubs_get_patent_by_number` 既有的 pub→guid 解析(line 343-400 已有此邏輯),再取全文。複用既有橋接,不新寫查詢語法。
- **DD-5**: claim1 空旗標。`gpss_to_records` 偵測 `claim1` 為空或剝掉樣板前綴(`"What is claimed is:"` / `"We claim:"` 等)後無實質內文 → 該 record 加 `claim1_empty: true`。`gpss_search` 結果不改主結構(向後相容),旗標在 records 層。
- **DD-6**: D1(uspc)/ D2(family)需先查 TIPO GPSS API 規格。**無本機規格文件**(refs/ 無 GPSS 文件)。決策:Phase 5 先以 webfetch 查 TIPO GPSS API 官方文件確認有無 US 分類欄位代碼;確認支援才加 `uspc` 參數,否則落 skill 文件樣板。**未確認不得臆造欄位代碼(反幻覺)**。
- **DD-7**: DD-7 (Phase 6 偵查結論): 無法取得 TIPO GPSS API 官方欄位規格(webfetch 只回 usage stub / gpss_doc 404 / 規格 PDF 需 userCode 認證,本機無)。GPSS 已確認欄位碼僅 PN/ID/TI/IN/PA/AB/CS(CPC)/CL/IC(IPC),無 US 分類欄位證據。依反幻覺原則,不臆造 uspc 欄位碼。決策:D1(uspc)與 D2(family)皆落 skill 文件——USPC 軸走 uspto_patents PPUBS CCL 樣板;family 記載「GPSS 去重=公開號級,epo_family 補家族」(後者既有 skill 已載,grounded)。gpss_search 不加 uspc 參數。

## Risks / Trade-offs

- **R1**: `fetch_patent_pdf` 預設行為改變 → 既有呼叫端(`extract_representative_figure`、batch figures)若沒同步傳 `allow_scraping=True`,TW 案抓圖會壞。緩解:Phase 1 同步改所有內部呼叫端,加測試。
- **R2**: 參數 alias 若處理不全 → validation error。緩解:逐工具加 alias + 測試兩種參數名都通。
- **R3**: D1/D2 規格查不到 → 退回 skill 文件記載路徑(本就是 BR 的備案建議)。

## Critical Files

- `src/patent_mcp_server/patents.py`: fetch_patent_pdf(2118)、extract_representative_figure(1619)、ppubs dispatcher(200-470)、patent_get_claim1(1173)、batch figures(2388)
- `src/patent_mcp_server/screening_table.py`: gpss_to_records(167)
- `src/patent_mcp_server/gpss/client.py`: search(94)
- `skills/patentworks/SKILL.md`: §5(line 39-55)
- `tests/`: 既有測試結構待查

## Validation

- 每 phase 後跑既有測試 + 針對性新測試。
- A1: 預設 `fetch_patent_pdf` 對純 TW 案(只有 gpss 來源)回 SCRAPING_REQUIRED;傳 allow_scraping=True 才抓。
- A2: 每工具用舊名 + 新名各呼叫一次都通。
- A3: 掃描版 PDF 回 image_count 而非裸 NO_FIGURE_PAGE。
- B1: US 空 claim 案的 record 帶 claim1_empty=true。
