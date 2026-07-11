# Changelog

本檔為 patentmcp 的變更紀錄(繁體中文)。早於 2026-07-06 的歷史見 git log 與 `specs/` 各 plan 套件。

## 2026-07-11

### Added

- **R16 domain-KB self-shipping(plan `mcp_r16-domain-kb`,依 `opencode/specs/mcp-integration-standard` §R16)**:新增 `patentmcp_kb_query(q, type?, limit?)` + `patentmcp_kb_get(id)` 兩個 read-only MCP tool,in-band 查詢 repo 的 ragbase 專利實務知識庫(`.specbase/ragbase.sqlite`,21 筆 evidence-graded 物件)。查詢語義比照 specbase / bodesign reference impl(全 token ≥3 碼點→FTS AND、全 <3→LIKE scan、混合→hybrid,payload 帶 `matchMode` 自述降級);唯讀由連線層強制(URI `mode=ro` + `PRAGMA query_only=ON`,目錄 rw 掛載僅為 WAL side files);KB 缺失回 `{success:false, error_code:"KB_UNAVAILABLE", remedy}` fail-fast。compose 新增 `./.specbase:/var/lib/patentmcp/kb` 掛載 + `PATENTS_KB_DB` env;mcp.json 0.5.0 + R16.5 recall-first signpost;patentworks SKILL.md 增 recall-first 紀律(R15 guide 同步生效);5 個判斷密集工具(patent_search / patent_bulk / pool_fetch / gpatents_get / ppubs_batch_get_claims)description 加 `consider: patentmcp_kb_query`。tool surface 36→38。驗證:`tests/test_kb_tools.py` 12 tests + 全套 199 passed;live MCP rail smoke(kb_query "GPSS" fts 7 hits、kb_get 全文+provenance);TV-6 兩門一致性(gate.ts ragbase_query 與 in-band 同 query 同 id 集合,diff 為空)。

## 2026-07-06

### Added

- **檢索工具改名緩衝 stub(BR_20260706)**:`gpss_search` / `epo_search` / `gpatents_search` 以 deprecation stub 形式重新註冊一個版本週期,呼叫回 typed error `{success:false, error_code:"TOOL_RENAMED", use:"patent_search"}`,不執行舊邏輯。讓 stale skill 投影 / 舊劇本第一次呼叫就被糾正,而非落 unknown-tool 迴圈。測試:`tests/test_tool_renamed_stubs.py`。

### Fixed

- **`gpss_download_patent_pdf` unpack 崩潰(BR_20260706,已 closed)**:`_gpss_iter_result_rows` docstring 宣稱 yield 4-tuple(含 link02_href)但實際只 yield 3-tuple;消費端 `_gpss_select_harder_path` 依 docstring 做 4-way unpack,凡 GPSS 結果列表非空必炸 `not enough values to unpack (expected 4, got 3)`(no-match 案件因迴圈體未執行而倖存,造成「部分案件才炸」假象)。修復:消費端改 3-way unpack + docstring 同步。驗證:rebuild 容器後重跑 BR 三案號 — CN120932368A / US20250275686A1 回 typed no-match error,CN120564339A 成功下載 PDF(459653B);unpack 錯誤不再出現。BR 移至 `issues/closed/`。
- **patentworks skill XDG 投影過期(BR_20260706 D1)**:投影(`~/.local/share/opencode/skills/patentworks/`)仍為 06-28 快照,教 AI 呼叫已下架的 `gpss_search`(實測 ~30 次 unknown-tool)。已以 SSOT(`skills/patentworks/`)重新同步投影並重建 manifest。

### Documented

- **補記 `7c4330d`(2026-07-03, mcp.json 0.3.0)檢索統一 rename 對照表**(當時未文件化):

  | 舊工具 | 去向 |
  |---|---|
  | `gpss_search` | → `patent_search`(來源梯內建,GPSS 為首選級;參數 `cpc`/`ipc`/`keyword`/`keyword_field`/`applicant`/`pub_number`/`date_from`/`date_to`/`databases`/`num`/`skip` 沿用;`patent_type`/`case_type`/`fields`/`inventor_country` 下架) |
  | `epo_search` | → `patent_search`(EPO 級內建;CQL 介面下架,改結構化參數;單號工具 `epo_family`/`epo_biblio` 保留) |
  | `gpatents_search` | → `patent_search(allow_scraping=True)`(爬蟲尾級閘控;單號工具 `gpatents_get`/`gpatents_download_*` 保留) |
  | `uspto_patents` 的 `ppubs_search_*` methods | → `patent_search`(PPUBS 級內建;全文/單號 methods 保留) |
