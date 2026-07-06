# PatentWorks

專利從 idea 到申請的全流程工作站 —— 一個 **MCP server + skill 組合包**,設計為與 OpenCMS、docxmcp、drawmiat 串接。

> 本專案於 2026-06 全面重定位並與其 AGPL 前身**斷開血脈**,以 MIT 重新授權。歷史、舊 8 層多 Agent 架構(A0–A8)、HLS/Grafcet 實驗等皆已廢除;產品由下列兩塊構成。

## 組成

### `patentmcp`(MCP server,`vendor/patents-mcp/`)
專利資料檢索與檔案交付。fork 自 openpharma/patents-mcp(MIT)並擴充:
- **檢索**:`patent_search`(**單一檢索入口**,來源梯內建:TIPO GPSS 官方 API 首選 → EPO OPS → USPTO PPUBS → gated Google Patents 爬蟲;依憑證與查詢軸自動路由,每級嘗試記入 `provenance`;爬蟲尾級須 `allow_scraping=true` 明確授權,否則官方全 miss 即 `SCRAPING_REQUIRED` fail-fast)。
  - 舊分散檢索工具已下架:`gpss_search`、`epo_search`、`gpatents_search`、`uspto_patents` 的 `ppubs_search_*` methods → 一律改用 `patent_search`。單號取文工具(`epo_family`/`epo_biblio`/`gpatents_get`/`ppubs_batch_get_claims`/PPUBS 全文)保留。
- **取文/產物**:`gpatents_get`(完整摘要+claims)、`gpatents_download_pdf/figure`(代表圖/PDF)。
- **R13 compute/landing 兩平面(2026-07, plan `patentmcp_webdav-r13-refactor`)**:依 `mcp-integration-standard` §R13,container tool 只管**網路/憑證取得**(compute plane);確定性後處理落地為 **repo-local skill scripts**(landing plane)。
  - **建表**:`patent_search` 取 records JSON → 本地 `skills/patentworks/scripts/screening_build.py`(家族去重→切 Claim1→欄位隨選 CSV;>300 擋下)。舊 `build_screening_table` 已下架為 `TOOL_LANDED` redirect。
  - **其他 landing scripts**:`claims_tools.py`/`search_audit.py`/`figure_extract.py`/`pool_charts.py`/`patentdb_local.py`(皆 `python3 <script> --help`)。`search_audit`/`patentdb_*`/`extract_representative_figure`/`patentmcp_analyze_pool` 同步下架為 redirect;新增 `pool_fetch`(pool 取數半段)。
- **檔案交付 / WebDAV working cache**:docxmcp 式 token+blob store(`/files/{token}/blob/{rel}`)+ **online 掛載工作區** `/dav/{subject}/{rel}`(class-2 WebDAV,per-owner Basic auth,無 identity fallback)。lifecycle 工具 `cache_provision`→mount PUT 投料→`cache_export`(顯式 N:M 落地)→`cache_close`(dirty gate)。`stage_file` 已由 provision+DAV PUT 取代(下架)。bytes 不過 context。
- **端點**:`/mcp`(Streamable HTTP)、`/`(landing)、`/tools`(機器可讀工具 schema,取自 live registry,錯誤直接 500 不靜默)、`/health`(liveness;`/healthz` 為相容別名)、`/files/{token}/blob/{rel}`、`/skills/patentworks.zip`。
- **生命週期**:`webctl.sh {start|stop|restart|refresh|health|clean|purge}`;`scripts/patentmcp-self-heal.sh {--check|--heal}` 探測 UDS socket,不健康時只重建 `patentmcp-${USER}` compose project(不另起 daemon)。

### `patentworks`(skill,`skills/patentworks/`)
專利從業流程,三個 flow 可單用或串成完整旅程:
```
disclosure(交底書)→ screening(查新)→ drafting(起草說明書)
```
- **disclosure**:原始材料/idea → 結構化技術交底書(intake 問題集、專利點挖掘、脱敏、自檢)。
- **screening**:CPC 錨定、US/CN、≤300 件、家族去重、逐列消化評分 → Agent 友善、人類可讀 scored CSV。內分「可專利性」與「landscape」。
- **drafting**:claims-first → spec 支持 → 法遵自檢。法域分 **共通/TW/CN/US/EP**;法遵以 skill 知識處理,不做工具。

領域骨幹見 `skills/patentworks/patent-practitioner-workflow.md`。

## 近期變更

- **2026-07-06**:修復 `gpss_download_patent_pdf` unpack 崩潰(BR_20260706,已 closed)— 生成器 yield 3-tuple 但消費端 4-way unpack,GPSS 結果列表非空必炸;已修正並以 BR 三案號驗證(typed no-match / 成功下載)。另含檢索工具改名 stub 與 skill 投影同步,詳見 `CHANGELOG.md`。

## 設定

`.mcp.json`(gitignored,含憑證路徑)註冊 patentmcp;以 `uv --directory vendor/patents-mcp run patent-mcp-server` 啟動。檢索來源金鑰:
- Google Patents:免認證,已可用。
- TIPO GPSS:`GPSS_USER_CODE`(向 TIPO 申請)。
- Google BigQuery(選用):`GOOGLE_CLOUD_PROJECT` + `GOOGLE_APPLICATION_CREDENTIALS`。
- EPO OPS(規劃中):OAuth consumer key/secret。

## 設計原則

- **輸出不變式**:任何檢索的最終交付物一律是 Agent 友善、人類可讀的 CSV 表格,經 token+blob handle 交付。
- **AI 預篩/起草草稿 + 解釋,人類複核裁決**(專利有法律份量)。
- **大道至簡**:不重造 docxmcp / drawmiat / OpenCMS 已能服務的子系統。

## 參考材料

`refs/` 收錄三個外部專利相關專案供研讀(各自授權;見 `refs/README.md`)。**AGPL 來源(PatentWriterAgent)僅供研讀,其程式碼不得進本產品。**

## 授權

MIT,見 [LICENSE](LICENSE)。
