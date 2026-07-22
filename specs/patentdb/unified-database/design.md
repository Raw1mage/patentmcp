# Design: patentdb_unified-database

## Context

承 proposal：patentdb 升級為「實體 blob 層 + 結構化資料層」雙層架構，核心哲學是**被動累加收集**（稀疏、漸進、先查本地後補）。本檔釘死 sqlite schema、工具 API、與既有程式碼的接線點，供使用者審核後再寫 code。

核實基礎（已驗證）：
- `_get_db_root()`（patents.py:884）已解析 patentdb 根（`PATENTS_DB_ROOT` env 或 `.mcp.json` 錨點）。
- `_find_local_patent_cache` / `_save_local_patent_cache`（L938/947）已做 blob 讀寫，但只 pdf/xml、metadata 是 4 鍵 stub、figures 未入庫。
- 三個下載工具已接 cache：`gpss_download_patent_pdf`（L1933/2030）、`gpss_download_patent_xml`（L2083/2182）、`fetch_patent_pdf`（L2245/2283/2337）。
- patentmcp 既有 sqlite 範式：`bq_usage.sqlite`（計費帳本）、`.specbase/*.sqlite`。

## Goals / Non-Goals

### Goals

- 給 patentdb 一個跨專案結構化書目層（sqlite），可全文檢索、可 query、可跨案複用。
- 把 candidates.csv 的書目+評分沉澱進 DB，但不廢除 CSV（CSV 為專案視圖）。
- schema 容忍稀疏，register 不要求完整，upsert 漸進合併。

### Non-Goals

- 不做雲端同步/多人鎖。
- 不引入 ORM。
- 不主動爬全網建庫。

## Decisions

### DD-1：sqlite 落 `patentdb/patentdb.sqlite`，與 blob 層同根
沿用 `_get_db_root()`，DB 檔放 patentdb 根目錄。理由：blob 層與結構化層同源同根，備份/搬移一致；符合既有 `bq_usage.sqlite` 單檔 sqlite 範式。

### DD-2：全域 DB 只管書目，screening 評分不進庫（核心修正）
screening（relevance/技術要點/命中要件/評分理由）是 **by-project** 的判斷——專案視角、會變、跨案不同。它是專案工作產物，不是全域書目庫該管的事。全域 patentdb 只承載「書目事實」這一種跨案恆定、可複用的客觀真相。
- `patentdb.sqlite` 只有兩個物件：`patents`（書目）+ `patents_fts`（全文）。**無 screenings 表。**
- screening 評分留在專案的 `02_pool/candidates.csv`（中間產物），隨專案走，不入全域庫。
- 理由：把專案評分塞進百萬級全域書目庫，只會污染唯一真相、讓書目庫背上無關的專案包袱、且評分跨案矛盾無法調和。書目是事實（一件一列），評分是觀點（隨案而異）——兩者物理隔離。

### DD-3：所有書目/claim/blob 欄位 nullable（被動累加哲學的 schema 落實）
register 不要求完整——一件專利可以只有 pubno+標題先入庫。完整度是查詢結果屬性（completeness flags），非入庫前提。

### DD-4：upsert 漸進合併，不覆寫既有非空值
`patentdb_put` 補欄位時，COALESCE 既有非空值；只填補 NULL 欄。明確覆寫需傳 `overwrite=true`。理由：被動累加下，後到的部分資料不應抹掉先前較完整的資料。

### DD-5：FTS5 over 標題/摘要/claim1，external-content 模式
`patents_fts` 用 FTS5 external-content（內容指向 patents 表，不重複存），triggers 同步。理由：省空間，與 specbase wiki FTS 範式一致。

### DD-6：blob 不進 DB，DB 只存路徑+sha256
PDF/XML/figures 實體仍落檔案系統 `<國別>/<號>/`，DB 存相對路徑+sha256+完整度旗標。理由：sqlite 不適合存大 blob；blob 層與結構化層職責分離。

### DD-7：register 是下載工具的 side-effect，非阻斷主流程
既有下載工具下載成功後呼叫 `patentdb_register`（內部函式），失敗只 logger.warning 不中斷下載（同既有 `_save_local_patent_cache` 的 try/except 風格）。理由：DB 是疊加增益，不應讓 DB 故障擋住檢索主線。但這**不是 silent fallback 掩蓋問題**——register 失敗會記 warning + 可由 `patentdb_query` 完整度旗標查出缺漏。

### DD-8：figures 入庫 + 完整 metadata 補齊
`_save_local_patent_cache` 擴充 `file_type=figure`（存 `<號>/figures/<name>`）；metadata 從 4 鍵 stub 升級——caller 提供完整書目時寫完整 metadata.json，並同步 register 進 sqlite。

### DD-9：成本加權收集判準（收集價值 = 重抓成本，核心策略）
被動累加不等於「什麼都囤」。**收集的價值由「出去重抓的成本」決定——貴的才收集，免費就能現查的不囤。** 這是 patentdb 存在的經濟理由（小本經營負擔不起全量囤積）。

| 來源 | 重抓成本 | 收集策略 |
|---|---|---|
| BigQuery `google_*` | **高**（按掃描量計費，曾單次 10TB/$60） | **必收**——抓到的 claims/全文/書目一律入庫,絕不重抓 |
| EPO OPS（family/biblio） | **高**（每週 4GB 上限，超額斷線） | **必收**——family/biblio 入庫 |
| 同意爬取（GPSS headless 圖/PDF、batch_download_figures） | **高**（耗同意成本 + 限速單線 + 易被封） | **必收**——爬來的 PDF/圖一律落 patentdb,不重爬 |
| USPTO PPUBS 全文 | **中**（需多段 guid 解析,慢） | **收**——逐字 claims/全文入庫 |
| GPSS REST `gpss_search` 書目查詢 | **低/免費**（官方 REST,隨時可重打） | **不強制囤書目欄位**——現查即可;但若已連帶撈回 claim1/摘要則順手入庫(邊際成本為零) |

落實到工具行為：
- `patentdb_register`（下載工具 side-effect）對**高成本來源的產物**一律入庫;對純 GPSS REST 免費書目查詢,只在「順手已取得」時入庫,不為了補書目而額外打免費 API 再寫。
- `patents` 表加 `acquisition_cost` 欄（`high`/`medium`/`low`/`free`，記該筆書目/blob 的取得成本來源），讓 `patentdb_query` 能回報「這筆是貴資料、別輕易丟」。
- **判準一句話**：免費可再生的不必囤,貴的/限額的/需同意的一旦取得就務必沉澱——quota 與同意成本不可重複支付。

**粒度從簡（使用者定調）**：`acquisition_cost` 只記粗分級（`high`/`low`，或加 `free`），**不精算實際 bytes/quota 花費**。理由：patentdb 的收集策略是「**被動累加基本常用資訊以加速日常工作**」，不刻意去撈偏門冷僻的東西來浪費自己的資源與時間。既然不主動追逐稀有資料,就不需要精細成本會計——粗分「貴/免費」足以驅動「取得過的貴資料別重抓」這唯一實際決策。常用領域自然在日常檢索中累積,偏門的本來就不必為了建庫而專程去撈。

### DD-10：百萬級書目量的 scale 設計
patentdb 是獨立的全域書目資產，目標承載 ≥百萬件等級。schema 須為此設計：
- **pubno 為 TEXT PRIMARY KEY**：sqlite 自帶唯一索引，百萬列精查仍 O(log n)。
- **二級索引**：country / family_id / application_date / acquisition_cost 各建索引（常見過濾軸）。
- **FTS5 external-content**：全文表不複製書目本體，只建倒排索引，百萬列下空間可控。
- **WAL 模式 + 批次 transaction**：自動腳本批次匯入時包在單一 transaction，避免逐列 fsync。
- **JSON array 存 applicants/CPC**（不另開關聯表）：百萬級下避免 join 爆炸；查詢以 pubno 精查 + FTS 為主，不做複雜多表關聯。
- **不存 blob 進 DB**（DD-6）：blob 在檔案系統，DB 只存路徑——百萬列 DB 檔身維持輕量（純文字書目，估每列 ~2-5KB，百萬列約 2-5GB，sqlite 可輕鬆處理）。
- **VACUUM/ANALYZE 定期維護**：自動腳本附帶選項。

### DD-11：CSV 落地即吸收——register 掛在 search tool 的 CSV 落地點（不花額外 toolcall）
patentdb 的擴充**平行於專案分析工作、零額外 toolcall**。最省的觸發點是：**search tool 拿到 CSV 結果的那一刻，順便 inline 吸收進 patentdb**——不需要獨立背景腳本、不需要 AI 額外呼叫 import。

- **接點**：`build_screening_table`（既有工具，已把候選集 LAND 成 token store 的 CSV，patents.py L985）在 CSV 寫完後，**inline 呼叫 `patentdb_store.import_csv`**，把書目吸收進全域庫（只書目，不吸評分 DD-2）。同理 `gpss_search` 若帶回 claim1/摘要等貴欄位也順手 register。
- **零成本**：CSV 已經在手（search 剛產出），吸收是純本機 sqlite upsert，無網路、無額外 API、無額外 toolcall。對 AI 工作迴圈完全透明。
- **side-effect 紀律（同 DD-7）**：吸收失敗只 logger.warning 不阻斷 search 主流程；失敗可由 `patentdb_query` completeness 查出。
- **成本加權（DD-9）**：吸收時對貴來源產物（claim1/全文/family）必收；純免費書目欄位順手收（邊際成本為零）。
- `patentdb_import_csv` 工具仍保留作**手動補吸**入口（補歷史 CSV、或 search 接點未覆蓋的來源），但**預設路徑是 search tool inline 觸發**，非 AI 手動、非 cron。
- 取捨：放棄「獨立背景腳本掃全專案」的設計——那要嘛 cron（環境依賴）、要嘛 AI 額外呼叫（花 toolcall）。掛在 search 落地點是邊際成本最低、且資料最新鮮（剛撈到就入庫）的觸發。歷史既存 CSV 的回填用 `patentdb_import_csv` 手動補一次即可。

### DD-12：AI 分析腳踏兩條船（search 檔案 + patentdb 並用）
專案分析時 AI 同時用兩個資料源，一併納入報告：
1. **本案 search 檔案**（`01_search/raw/` + `02_pool/candidates.csv`）：本次檢索的一手結果，主分析標的。
2. **patentdb 全域庫**：呼叫 `patentdb_query`（FTS 或分類過濾）查庫裡是否有**本案沒撈到、但適合的分析標的**——跨案累積的前案可能正中本案要害。
- 流程接點（priorsearch.md §3）：召回階段除了線上檢索，**並行查 patentdb**；命中的庫存標的併入 candidates 池（標來源 `from_patentdb`），一起評分、一起進報告。
- 價值：庫越大，新案越省 quota（已有的直接用）、覆蓋越廣（撈到別案查過的前案）。這是 patentdb 對專案的正回饋——養庫不只省成本，還提升每個新案的檢索品質。

## Schema (DDL 草案，待審)

```sql
-- 全域書目事實：一件專利一列
CREATE TABLE patents (
  pubno            TEXT PRIMARY KEY,        -- 正規化公開號 (TWI854998B / US20230081319A1)
  country          TEXT NOT NULL,           -- TW/US/CN/EP/WO
  normalized_no    TEXT NOT NULL,           -- I854998 / 20230081319
  kind             TEXT,                    -- A/B/U... (公開/公告種別)
  title_orig       TEXT,                    -- 原文標題
  title_en         TEXT,                    -- 英文標題
  abstract         TEXT,
  claim1           TEXT,                    -- 逐字 Claim 1
  applicants       TEXT,                    -- JSON array
  inventors        TEXT,                    -- JSON array
  application_no   TEXT,
  application_date TEXT,                    -- YYYYMMDD
  publication_date TEXT,
  priority_date    TEXT,
  cpc_codes        TEXT,                    -- JSON array
  ipc_codes        TEXT,                    -- JSON array
  family_id        TEXT,                    -- INPADOC family
  -- blob 層完整度旗標 + 指標
  pdf_path         TEXT, pdf_sha256   TEXT,
  xml_path         TEXT, xml_sha256   TEXT,
  figures_json     TEXT,                    -- JSON array of {name,path,sha256}
  -- 來源/累加 provenance
  first_source     TEXT,                    -- gpss/epo/uspto/google/manual
  scraping_used    INTEGER DEFAULT 0,       -- 是否經同意爬取
  created_at       TEXT, updated_at TEXT
);

-- FTS5 全文（external-content 指向 patents）
CREATE VIRTUAL TABLE patents_fts USING fts5(
  pubno UNINDEXED, title_orig, title_en, abstract, claim1,
  content='patents', content_rowid='rowid'
);
-- + INSERT/UPDATE/DELETE triggers 同步（DDL 完整版於實作）

-- (無 screenings 表 — 評分是 by-project 產物，留在專案 candidates.csv，見 DD-2)

-- 百萬級索引（DD-10）
CREATE INDEX idx_patents_country      ON patents(country);
CREATE INDEX idx_patents_family       ON patents(family_id);
CREATE INDEX idx_patents_appdate      ON patents(application_date);
CREATE INDEX idx_patents_acq_cost     ON patents(acquisition_cost);
-- pubno 已是 PRIMARY KEY（自帶唯一索引，精查 O(log n)）
```

## Tool API (待審)

### `patentdb_put(pubno, fields={}, blobs={}, overwrite=false)`
Upsert 一件專利書目。`fields` 為書目欄位 map（全可選）；`blobs` 為 {pdf/xml/figures 路徑}。漸進合併（DD-4）。回 {pubno, created|updated, completeness}。

### `patentdb_query(pubno=None, fts=None, country=None, limit=20)`
全域書目庫查詢（無 project 維度——評分不在庫，DD-2）。
- `pubno`：精查一件，回完整書目 + completeness flags（哪些欄位/blob 有無）。
- `fts`：FTS5 全文檢索（標題/摘要/claim1），回 pubno+snippet+rank。
- `country`/分類過濾：列符合條件的書目（百萬級下用二級索引，DD-10）。
回結果含 completeness，讓 caller 判斷是否需補（被動累加：缺才出去撈）。**這是 AI 腳踏兩條船（DD-12）的庫側入口**——分析時查庫找本案沒撈到的標的。

### `patentdb_import_csv(csv_path)`
**只匯入書目欄位**（pubno/標題/摘要/claim1/CPC/...），**不碰 screening 評分**（評分留在專案 CSV，DD-2）。每列 → patents upsert（漸進合併）。回 {imported, updated, skipped}。
- 預設由背景自動腳本 `scripts/patentdb_absorb.py` 呼叫（DD-11），不勞煩 AI。
- 成本加權（DD-9）：吸收時對貴來源產物（claim1/全文）必收，純免費書目欄位順手收。

## Risks / Trade-offs

- **R1 CSV↔DB 欄位映射漂移**：candidates.csv 欄位格式（priorsearch.md §0）若改，import 要同步。緩解：import 以欄位名映射，不靠位置；映射表寫進 design + skill。
- **R2 pubno 正規化不一致**：同件專利不同來源格式（US20230081319A1 vs US-2023-0081319-A1）可能重複入庫。緩解：複用既有 `_get_patent_country_and_normalized_no` 正規化後當 key。
- **R3 register side-effect 拖慢下載**：緩解：register 是輕量 sqlite upsert（無網路），且 try/except 不阻斷（DD-7）。
- **R4 FTS external-content trigger 維護成本**：緩解：標準 FTS5 範式，一次寫對；與 specbase 既有實作對齊。
- **Trade-off：不正規化 applicants/CPC 為獨立表**：用 JSON array 存。被動累加+小本經營下，查詢需求以 pubno 精查 + FTS 為主，不做複雜關聯查詢，JSON 夠用且 schema 簡單。

## Critical Files

- `src/patent_mcp_server/patentdb_store.py`（新）：schema + put/query/import 純函式 + register。
- `src/patent_mcp_server/patents.py`：+3 `@mcp.tool()`、既有下載工具接 register、`_save_local_patent_cache` 擴充。
- `patentdb/README.md`：雙層架構。
- `skills/patentworks/flows/priorsearch.md` §5：I/O 現況修正 + import_csv 接線。
