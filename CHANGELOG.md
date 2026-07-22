# Changelog

本檔為 patentmcp 的變更紀錄(繁體中文)。早於 2026-07-06 的歷史見 git log 與 `specs/` 各 plan 套件。

## 2026-07-21

### Documented

- **README 全面重寫(使用者/導入導向)+ IDEF0/GRAFCET 圖解**:舊 README 偏架構清單,重寫為「這是什麼→四大功能群→主旅程→快速上手」的導入叙事。新增 `docs/diagrams/` 四張 drawmiat 渲染 SVG:**IDEF0 A0**(功能總覽,A1檢索/A2取文/A3交付/A4 skill 四功能群 + ICOM)、**IDEF0 A1**(檢索來源梯 GPSS→EPO→PPUBS→爬蟲分解)、**IDEF0 A4**(disclosure→screening→analysis→drafting 四 flow)、**GRAFCET 主旅程狀態機**(screening 後 or-分岐輕量/重型、analysis 回流 screening 精雕迴圈)。圖源 JSON(`patentworks_idef0.json`/`patentworks_grafcet.json`)一併入版,經 `specbase_diagram_validate` 兩類均過。

### Added

- **R17 minimum operational toolset + host mediation(plan `patentmcp_r17-minimum-operational-toolset`,依 `opencode/specs/mcp-integration-standard` §R17)**:在既有已達標的 R17.1(a/b)/R17.4/R17.5 之上補齊三個 gap。
  - **R17.1(c) portable result retrieval**:新增 `_resources.py` + FastMCP 註冊,每個 token-store 產物可經 `resources/read` @ `patent://{token}/{rel}` 以**協定原生**方式取得(免 host-private 的 `/files/{token}/blob` 或 WebDAV `/dav` 擴充);`resources/list` 動態 mirror live token store(覆蓋 `_resource_manager.list_resources`,產物為 runtime 鑄造故非靜態註冊)。unknown token/rel 與路徑逃逸沿用 blob 面的 `_safe_target` fail-loud,絕不空讀。blob/WebDAV 面不移除、續作 host accelerator。
  - **R17.1.1 結構化 capability summary**:`patentmcp_init` 由 prose-only 加寬為 `{doctrine, capabilities}`,每個 endpoint 標 `visibility=container|host-visible`(container UDS socket path 不被誤認為 host-executable);`prompts/get` 維持 prose-only,doctrine 兩 face byte-identical(R15.5 no-drift,`_capabilities.py`)。
  - **R17.2.4/5 typed asset preflight + content assertions**:新增 `_delivery.py`(pure module)並接線 `cache_export` delivery gate。空工作樹以 `EXPORT_EMPTY` 拒交付(nothing lands,transport-valid 但 empty 不得報 delivery-ready);caller 可帶 opt-in content assertions(`assert_nonempty`/`assert_min_files`/`assert_contains_rel`),不符即 fail-loud `ASSERTION_FAILED`。
  - **驗證**:`tests/test_r17_conformance.py` 端到端雙跑(portable-floor `resources/read` 無 WebDAV / WebDAV `cache_export`+assertions 空拒)+ `test_resources.py` / `test_delivery_preflight.py` / `test_init_capabilities.py`;全套 361 tests 綠。mcp.json 0.5.0→0.6.0 + R17 signpost;`specs/architecture.md` Critical File Index 補三新模組;issue 移至 `issues/closed/`。

## 2026-07-13

### Changed

- **代表圖來源梯改為全國別 GPSS 爬圖優先 + PDF pipeline fallback**:`patentmcp_batch_download_figures` 原本僅 `TW` 走 GPSS 爬圖、所有非 TW 一律走 PDF pipeline(`extract_representative_figure` — 需先取整份 PDF 再本地 poppler 渲染)。改為**所有國別**先試 `_GpssScrapeSession.fetch_representative_figure`(GPSS 詳情頁單次爬取即得全解析度 G2 代表圖,最便利現成,且 country-agnostic + 內建 neighbour-guard 號碼核對);僅當 GPSS miss(近期公開尚未入 image庫 / Cloudflare 擋 / 詳情頁無圖)才 fallback 到 PDF pipeline。共用 session 的 cookie/cf_clearance jar 跨全部 item 重用。雙層皆 miss 時該筆 skip 並回 `{gpss_error, pdf_error, tried:[gpss,pdf_pipeline]}` 記錄兩層均嘗試。503 cooldown 與 failure isolation 語義保留。驗證:`tests/test_gpss_session_batch.py` 8 tests(含新增 GPSS-first-all-jurisdictions / gpss-miss-fallback-to-pdf / both-tiers-miss-combined-error 三 case)全過;鄰近 `test_br20260628_figures.py` + `test_br20260628_tooling_gaps.py` 共 38 tests 無回歸。

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
