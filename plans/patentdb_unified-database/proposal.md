# Proposal: patentdb_unified-database

## Why

`patentdb/` 目前只有「實體 blob 層」（PDF/XML + 由下載工具自動回存的極簡 metadata stub），缺一個「結構化書目層」。每個檢索專案的 `candidates.csv` 都是孤島——跨案蒐集的書目、claim、CPC/IPC、相關性評分全部隨專案散掉，沒有跨案統一真相。

具體痛點：
- 同一件專利在 A 案查過、蒸餾過，B 案重新開檢索時無法複用既有書目，得重花 API quota 再撈。
- 已下載的實體（PDF/XML）有本地快取（`_find/_save_local_patent_cache`），但**書目欄位**（標題/申請人/claim1/CPC）沒有結構化索引，無法全文檢索、無法跨案 query。
- figures 完全沒入庫（`_save_local_patent_cache` 只接 pdf/xml），完整 metadata 靠手動填（工具自動建的 stub 只有 4 鍵）。

## Original Requirement Wording (Baseline)

- 「我們趁這個機會把 patentdb 的能力做完整一點好了。除了用檔案系統儲存文件本體之外，關於 csv 檔中收集的資料，也應該要成為一個 unified database。」

## Requirement Revision History

- 2026-06-28: initial draft created via plan-init.ts
- 2026-06-28: 填充雙層架構與根因（基於核實：patentdb I/O 已接線於 `_find/_save_local_patent_cache`，但只 pdf/xml、metadata stub、figures 未入庫、無獨立 query/put 工具）

## Effective Requirement Description

把 patentdb 從「純實體檔案庫」升級為「實體 blob 層 + 結構化資料層」雙層架構：

1. 新增 `patentdb.sqlite`（跨專案統一結構化層），與既有 `<國別>/<正規化號>/` 實體 blob 層並存。
2. sqlite 存全域書目事實（一件專利一列）+ FTS5 全文檢索 + 專案×專利的評分判斷（screening）分表。
3. 新增工具：`patentdb_put`（upsert 書目+blob 註冊）、`patentdb_query`（pubno 精查 / FTS）、`patentdb_import_csv`（candidates.csv 批次入庫）。
4. 既有下載工具（gpss_download_pdf/xml、fetch_patent_pdf）下載後自動 register 進 sqlite。
5. 補齊 figures 入庫 + 完整 metadata（非 stub）。

CSV 不廢除——CSV 是專案工作/稽核視圖（人可編、build_xlsx 讀它），DB 是跨案累積記憶。新專案開檢索先查 DB 預填已知專利（省 quota），收尾時 CSV → DB import。

## Scope

### IN
- `patentdb.sqlite` schema（patents / patents_fts / screenings 三表）
- `patentdb_put` / `patentdb_query` / `patentdb_import_csv` 三個 MCP 工具
- 既有下載工具自動 register 書目進 sqlite
- figures 入庫 + 完整 metadata（取代 4 鍵 stub）
- patentdb/README.md 更新雙層架構說明
- patentworks skill §5 修正 patentdb I/O 現況描述（接上新工具）

### OUT
- 廢除 candidates.csv（保留為專案視圖）
- 廢除既有 `_find/_save_local_patent_cache`（保留，內部接 sqlite register）
- 線上同步/雲端 DB（純本地 sqlite，同 bq_usage.sqlite / .specbase 範式）
- 自動爬取補圖（仍受 skill §5 同意天條約束）

## Non-Goals

- 不做跨機器的 DB 同步或多人協作鎖。
- 不改變 candidates.csv 的欄位格式（DB import 從既有格式讀）。
- 不引入 ORM 重框架——用 stdlib sqlite3，同 fleet 既有範式。

## Design Philosophy: 被動累加收集（Passive Accumulation）

patentdb 不是「一次建好的完整資料庫」，而是**被動累加的稀疏記憶體**——平常檢索到什麼就存什麼，需要的東西缺了才出去補，地端已有就直接用。這條哲學決定了 schema 與工具的根本性質：

- **Schema 必須容忍稀疏**：每件專利的書目欄位、claim1、figures、PDF/XML blob 全部**可選、可後補**（nullable / 漸進填充）。一件專利可以只有 pubno + 標題就先入庫，日後再補 claim、再補圖。**不得要求完整才允許 register。**
- **Upsert 是漸進式合併**，不是覆寫：`patentdb_put` 補欄位時，已有的非空欄位保留，只填補缺的（除非明確覆寫）。
- **「先查本地→未命中才補」是第一原則**：任何取用先查 patentdb，命中就用（省 quota），缺才出去撈，撈回來補進庫——庫於是隨使用自然長大。
- **完整度是查詢結果的屬性，不是入庫的前提**：`patentdb_query` 回傳時標明該件有哪些欄位/blob（completeness flags），讓 caller 判斷是否需補。
- **不主動爬全網建庫**：被動累加，不做批量預抓；規模隨實際檢索需求自然累積，符合「小本經營」的成本現實。

## Constraints

- 技術選型：stdlib `sqlite3` + FTS5，與 patentmcp 既有 `bq_usage.sqlite` + fleet `.specbase/*.sqlite` 一致，不引入新依賴。
- **稀疏容忍（承上哲學）**：所有書目/claim/blob 欄位 nullable；register 不要求完整；upsert 漸進合併不覆寫既有非空值。
- 全域書目（patents）與專案評分（screenings）**必須分表**：同一件專利在不同案有不同相關性評分（CN120543023A 對 iSafe2.0 是 5★，對別案可能無關），評分不能污染全域書目唯一真相。
- DB 路徑沿用 `_get_db_root()` 既有解析（`PATENTS_DB_ROOT` env 或 `.mcp.json` 錨點），sqlite 落 `patentdb/patentdb.sqlite`。
- fail-fast：DB 寫入失敗顯式報錯，不 silent fallback（符合 AGENTS.md 第11條）。

## What Changes

- 新增 `src/patent_mcp_server/patentdb_store.py`（sqlite 模組：schema 建置 + put/query/import 純函式）。
- `patents.py` 新增 3 個 `@mcp.tool()` 包裝 + 既有下載工具接 register。
- `_save_local_patent_cache` 擴充支援 figures + 寫完整 metadata。
- `patentdb/README.md` 補雙層架構。
- patentworks skill `flows/priorsearch.md` §5 修正 I/O 描述。

## Capabilities

### New Capabilities
- `patentdb_put`: upsert 一件專利的書目事實 + 註冊 blob 路徑/sha256 進 sqlite。
- `patentdb_query`: 依 pubno 精查或 FTS5 全文檢索庫存專利（標題/摘要/claim1）。
- `patentdb_import_csv`: 從 candidates.csv 批次匯入書目 + 該案 screening 評分。

### Modified Capabilities
- `gpss_download_patent_pdf/xml` / `fetch_patent_pdf`: 下載後除了回存 blob，額外 register 書目進 sqlite。
- `_save_local_patent_cache`: 支援 file_type=figure；自動 metadata 從 stub 升級為完整書目（若 caller 提供）。

## Impact

- 影響檔案：`src/patent_mcp_server/patents.py`、新增 `patentdb_store.py`、`patentdb/README.md`、`skills/patentworks/flows/priorsearch.md`。
- 影響工具表面：+3 工具（28 → 31）。
- 對既有專案：向後相容——既有 `<國別>/<號>/` blob 不動，sqlite 為疊加層；既有 candidates.csv 流程不變。
- 對 quota：正面——跨案複用書目，減少重複線上檢索。
