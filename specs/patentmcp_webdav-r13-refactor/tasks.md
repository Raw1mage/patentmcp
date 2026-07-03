# Tasks: patentmcp_webdav-r13-refactor

## 1. 純轉換抽出（R13 基座）

- [x] 1.1 建 `src/patent_mcp_server/_pure/`：從 screening_table.py 抽出 resolve_columns / dedup_by_family / build_csv / 四個 adapters / _claim1_is_empty；從 patents.py 抽出 clean_html_text / extract_claim1_text（stdlib-only，零網路）
- [x] 1.2 container 側 screening_table.py / patents.py 改 import `_pure`，既有測試全綠

## 2. Landing scripts（skills/patentworks/scripts/）

- [x] 2.1 `_lib/` vendored copy 機制 + hash 同步 test（drift fail-fast）
- [x] 2.2 `screening_build.py`：records JSON → dedup → columns → CSV（golden test：與舊邏輯 byte-equal）
- [x] 2.3 `claims_tools.py` + `search_audit.py`（搬移 + CLI 包裝，--repo/--in 參數契約）
- [x] 2.4 `figure_extract.py`（poppler precheck `MISSING_DEPENDENCY` fail-fast）+ `pool_charts.py`（matplotlib precheck）
- [x] 2.5 `patentdb_local.py`：put/query/import_csv over 本地 sqlite
- [x] 2.6 每個 script `--help` 印完整參數契約；typed JSON 錯誤，絕不吐 stack（R13.6 scope guard）

## 3. Container tool 面改造

- [x] 3.1 `TOOL_LANDED` redirect stub：build_screening_table / stage_file / search_audit / patentdb_* / extract_representative_figure / patentmcp_analyze_pool（含 usage 指引）
- [x] 3.2 新增 `pool_fetch`（analyze_pool 取數半段，回 records JSON handle）
- [x] 3.3 移除 build_screening_table 的 patentdb inline absorb；回歸測試綠

## 4. TokenStore 擴充（deliverable-cache）

- [x] 4.1 entry 新增 class / subject_id / owner_identity / last_export_at / credential_hash；rehydrate 相容舊 meta
- [x] 4.2 class-aware reaper：ephemeral 維持 3600s；deliverable-cache dirty 不 reap + safety-net 長 TTL warn-first
- [x] 4.3 mkdir / move helper（MKCOL / MOVE 用，traversal 防護沿用）
- [x] 4.4 dirty 判定：mtime/hash vs 上次 export 快照

## 5. WebDAV + Auth

- [x] 5.1 `_auth_provider.py`：per-owner credential 發放（hash 存放、constant-time 比對）+ owns()；401 帶 WWW-Authenticate，無 fallback
- [x] 5.2 `_dav.py`：OPTIONS/PROPFIND(0/1 multistatus)/GET/PUT/DELETE/MKCOL/MOVE/LOCK/UNLOCK + in-memory lock table（TTL）
- [x] 5.3 掛載 `/dav/{subject}/{rel:path}` 於 build_app extras（不引入第二 lifespan）
- [x] 5.4 MCP tools：cache_provision（idempotent）/ cache_list / cache_export（N:M、COPY、EXPORT_TARGET_UNREACHABLE）/ cache_close（dirty gate、force）
- [x] 5.5 rclone 實掛載驗證：mkdir(MKCOL)/rcat(PUT)/lsf(PROPFIND)/cat(GET)/moveto(MOVE)/copyto(COPY)/deletefile(DELETE) + 空 collection 可見 + 無認證 401 + 錯密碼 401 + 跨 token MOVE 403 → **rclone host 實掛 12/12 全綠**。整合驗證揪出並修 4 層 unit test 漏抓的真 bug：(a) PROPFIND rel 尾斜線→startswith 誤判 not_found；(b) list_files 只列 file→空 MKCOL dir 對 PROPFIND 隱形 + Depth:1 誤回整棵遞迴樹（改 stat_entry/list_dir 檔案系統感知）；(c) gateway prefix 烤進 base_href/Destination needle→href 對不上（lsf 空）+ 合法同 token MOVE 誤判 cross_token 403（改 request-path 推導、prefix-agnostic）；(d) COPY 未列入 DAV_METHODS→rclone copyto 405（新增 _copy handler）。回填 3 個 unit regression test（COPY/空 collection/Depth:1 語義）。

## 6. 宣告與文件同步

- [x] 6.1 mcp.json：version 0.4.0 + R13.5 兩平面 instructions
- [x] 6.2 skills/patentworks：SKILL.md 路由表 + flows/screening.md 改本地建表工作流 + DAV 三層心智/export 紀律
- [x] 6.3 README.md + specs/architecture.md 全貌同步
- [x] 6.4 全套測試（host venv）綠：`.venv/bin/python -m pytest tests/ -q` → **136 passed**（含 5.5 揪 bug 後回填的 3 個 regression test）；vendor-sync `scripts/sync_pure_lib.py` 無 drift。**container 整合驗證（本輪補做）**：`webctl.sh restart` rebuild+recreate → UDS `/health` ok、`/healthz` 200、`/tools` 31 tools（cache_* 全在、pool_fetch present、build_screening_table 已下架）、`/dav` OPTIONS 回 DAV:1,2 + 401 WWW-Authenticate。
