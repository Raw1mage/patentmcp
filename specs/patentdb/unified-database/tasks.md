# Tasks: patentdb_unified-database

> 執行紀律見 plan-builder §16。每完成一項即時勾選 + plan-sync。Phase 邊界寫 slice summary。

## 1. sqlite 結構化層核心（patentdb_store.py，只管書目）

- [x] 1.1 建 `src/patent_mcp_server/patentdb_store.py`：schema 建置（patents + patents_fts external-content + triggers 兩物件，**無 screenings 表**，全欄 nullable，含 acquisition_cost 欄 + 百萬級二級索引 DD-10）
- [x] 1.2 `_db_connect()`：沿用 `_get_db_root()` 解析路徑，DB 落 `patentdb/patentdb.sqlite`，首次自動建表（idempotent）、WAL 模式（DD-10）
- [x] 1.3 `put(pubno, fields, blobs, overwrite, acquisition_cost)`：正規化 pubno 為 key（複用 `_get_patent_country_and_normalized_no`）、漸進合併 upsert（DD-4 COALESCE 非空）、回 completeness
- [x] 1.4 `query(pubno|fts|country)`：pubno 精查回完整書目+completeness flags；fts FTS5 BM25；country/分類過濾走二級索引（DD-12 AI 腳踏兩條船的庫側入口）
- [x] 1.5 `import_csv(csv_path)`：解析 candidates.csv（欄位映射表見 design R1），每列→patents upsert（**只書目，不碰評分** DD-2），批次包單一 transaction（DD-10）

## 2. 工具接線（patents.py）

- [x] 2.1 加 `@mcp.tool() patentdb_put / patentdb_query / patentdb_import_csv` 包裝（薄殼呼叫 store 純函式）
- [x] 2.2 既有下載工具接 register side-effect（DD-7）：`gpss_download_patent_pdf/xml`、`fetch_patent_pdf` 下載成功後呼叫 store.put 註冊書目+blob，try/except 不阻斷、失敗 logger.warning
- [x] 2.3 `_save_local_patent_cache` 擴充：支援 file_type=figure（落 figures/）；metadata 從 4 鍵 stub 升級為完整書目（caller 提供時）
- [x] 2.4 acquisition_cost 標記：register 時依來源工具標 high/medium/low/free（DD-9 成本加權判準）

## 3. search tool 落地即吸收（DD-11，零額外 toolcall，inline 接線）

- [x] 3.1 `build_screening_table` CSV 落地後 inline 呼叫 `store.import_csv`（只吸書目，DD-2）：CSV 已在手→純本機 upsert，無網路、無額外 toolcall
- [x] 3.2 side-effect 紀律（DD-7）：吸收失敗 logger.warning 不阻斷 search 主流程；可由 completeness 查出缺漏
- [x] 3.3 成本加權吸收（DD-9）：對貴來源產物（claim1/全文/family）必吸；純免費書目欄位順手吸（邊際成本零）
- [x] 3.4 `patentdb_import_csv` 工具保留作手動補吸入口（回填歷史 CSV / search 接點未覆蓋來源），非預設路徑

## 4. 測試 + 驗證

- [x] 4.1 單元測試 `tests/test_patentdb_store.py`：稀疏 put（只 pubno+標題）、漸進合併不覆寫、FTS 命中、import_csv 只入書目、completeness flags
- [x] 4.2 工具註冊驗證：FastMCP registry 28→31 工具，patentdb_put/query/import_csv 在列
- [x] 4.3 端到端回歸：用 TWCID 既有 candidates_r2_scored.csv 跑 import_csv，驗證**只書目入庫（無評分）**、跨案 query 命中
- [x] 4.4 既有 entry 相容：TW/I854998 既有完整 metadata 不被 stub 覆寫
- [x] 4.5 百萬級 smoke：合成 ~10萬列批次 import，驗證 transaction 批次 + 索引查詢效能可接受（DD-10 抽樣驗證，非真跑百萬）

## 5. 文件同步 + 收尾

- [x] 5.1 `patentdb/README.md` 補雙層架構（sqlite 結構化層 + blob 層 + 成本加權收集判準 + 百萬級設計 + 背景吸收腳本）
- [x] 5.2 patentworks skill `flows/priorsearch.md` §5 修正 I/O 現況（接 patentdb_query，移除「靠手動填充」錯誤描述）+ §3 加 DD-12 腳踏兩條船（召回並行查 patentdb）+ republish XDG
- [x] 5.3 rebuild patentmcp 容器，驗證新工具線上可呼叫
- [x] 5.4 event_record 收尾 + plan 收斂 verified
