# Architecture

## System Overview
- Repo 名稱：PatentDrafter / PatentWorks。
- 當前 repo 的可觀察核心是 **PatentWorks = patentmcp MCP server + patentworks skill**，而不是舊版八階段 prompt agent 應用。
- 產品目標是把專利工作拆成三個可單獨使用、也可串接的能力層：`檢索`、`分析`、`撰寫`。
- `specs/architecture.md` 是後續規劃與實作的 current-state architecture SSOT；若 skill flow、MCP tool 或資料交付契約改變，必須同步本檔。

## Top-Level Directory Map
- `README.md`
  - 現行產品定位入口：PatentWorks 是 MCP server + skill 組合包。
  - 明確標示 2026-06 後已與舊 AGPL 前身斷開，舊 8 層多 Agent 架構、HLS/Grafcet 實驗等皆已廢除。
- `vendor/patents-mcp/`
  - `patentmcp` MCP server。
  - 提供 Google Patents、TIPO GPSS、USPTO、BigQuery 等專利資料檢索與取文能力。
  - 提供 `build_screening_table` 與 `stage_file`，把候選資料或成品落地成 token/blob handle，避免 bytes 進入模型 context。
- `skills/patentworks/`
  - 現行專利工作 skill。
  - `SKILL.md` 是 flow router；`flows/` 定義 disclosure、screening、drafting；`reference/` 保存交底書與法域撰寫知識。
- `skills/patent-practitioner-workflow.md`
  - 領域流程骨幹，記錄人類專利檢索、判讀、分析與報告產出方式。
  - 是設計檢索/分析 skill 邊界的重要依據。
- `refs/`
  - 外部專利專案參考材料。
  - 授權紅線：MIT 內容可借鑑；AGPL 來源僅供研讀，不得把程式碼複製進本產品。
- `output/`
  - 本地產出樣本，例如檢索 spreadsheet。
- `specs/`
  - `architecture.md`：全域架構 SSOT。
  - `20260320_repo-planner-specs-plan/`：現行 specbase/plan-builder package，需從舊 repo skeleton 重構為 PatentWorks 現況與後續分析技能切分契約。
- `.mcp.json`
  - 本地 MCP server 註冊，指向 `vendor/patents-mcp`。
  - 含本地憑證路徑設定；不得假設憑證可提交或可外流。

## Runtime / Workflow Model
- 現行主流程是 skill 編排 MCP/tool 產物的工作站：
  1. `disclosure`：使用者材料、idea、文件或專案內容 → 結構化技術交底書。
  2. `screening`：技術問題 + CPC/keyword → 專利候選召回、建表、逐列判讀、評分 spreadsheet。
  3. `analysis`：資料來源無關的理解/比對層，應可消化檢索 MCP 產物或使用者直接提供內容。
  4. `drafting`：以分析後的結構化結果與目標法域知識 → 請求項、說明書、摘要。
- `analysis` 是要獨立化的中介能力：不應假設資料一定來自 `screening` 或 `patentmcp`。
- `screening` 仍可內含「逐列消化/預篩」作為檢索交付物 enrich 步驟，但可重用的技術特徵抽取、要件對照、差異點歸納、最接近前案判斷，應沉澱為獨立 analysis contract。

## Canonical Data Flow
- 使用者材料路徑：user content / files / disclosure → `analysis` → `drafting`。
- 檢索材料路徑：`patentmcp` search/get/build table → screening spreadsheet / handles → `analysis` → novelty/feature matrix/drafting basis → `drafting`。
- 混合材料路徑：使用者交底 + MCP 前案 + shortlist full claims → `analysis` → claim boundary / technical difference / report → `drafting`。
- 成品交付契約：大型表格、PDF、圖、全文與 docx 類產物走 token/blob handle；模型回覆只提供白話摘要、決策點、handle 與必要引用。

## Module Boundaries
- **檢索層 (`patentmcp`, `screening`)**
  - 負責資料取得、CPC/keyword 查詢、候選去重、建表、取文、PDF/figure/fulltext handle 化。
  - 不負責最終法律裁決；只提供可稽核資料與 AI 預篩欄位。
  - **單一檢索入口(2026-07, plan `patentmcp_search-dispatcher`)**:`patent_search` 是唯一 SEARCH 工具;來源梯(GPSS→EPO→PPUBS→gated gpatents)內建於 `search_dispatcher.py`,呼叫者不選來源。舊分散檢索工具(`gpss_search`/`epo_search`/`gpatents_search`/`uspto_patents` 的 `ppubs_search_*`)已下架;單號取文工具保留。
- **分析層 (`analysis`, planned skill boundary)**
  - 負責把任意來源材料正規化為技術特徵、要件對照（Claim Chart）、差異點、FTO/無效/前案可專利性比對分析、drafting basis。
  - 輸入來源可為 `retrieval_mcp`、`user_provided`、`file`、`mixed`。
  - 輸出應是結構化、可被 drafting 使用的中間產物，而非直接綁定 CSV 或 MCP schema。
  - CSV 大檔的讀取、切批、抽樣、索引與分工策略由執行 agent 自主決定；架構只要求結果可稽核、來源可追溯、不可捏造證據。
- **撰寫層 (`drafting`)**
  - 負責依目標法域載入 `reference/drafting/common.md` 與 TW/CN/US/EP 法域知識。
  - 吃 analysis 產出的必要技術特徵、最接近前案、區別技術特徵、實施例與術語表。
- **文件/交付層 (token/blob handle + WebDAV working cache)**
  - 負責把大型或二進位交付物落地並回 token/blob handle。
  - **WebDAV working cache(2026-07, plan `patentmcp_webdav-r13-refactor`)**:token namespace 對 host 暴露成 online 掛載工作區。`/dav/{subject}/{rel}` class-2 method 表(`_dav.py`)+ per-owner Basic auth(`_auth_provider.py`)+ 4 個 lifecycle MCP tools(`cache_provision`/`cache_list`/`cache_export`/`cache_close`)。cache = deliverable-cache class(TokenStore 擴充),ephemeral working tree;truth store 為家,`export` 顯式落地(N:M COPY),`close` dirty gate。`stage_file` 已由 provision+DAV PUT 取代(下架)。**R14.6 MCP-rail credential bootstrap(2026-07-06, BR_20260706)**:`cache_provision(issue_webdav_credential=true)` 走 MCP socket 直接 mint-or-rotate 該 cache 的 Basic credential(socket==capability,無 HTTP 雞生蛋;flag 省略時 payload byte-identical,天條 §11)。
- **本地計算層 (R13 landing plane, skill scripts)**
  - **R13 compute/landing split(2026-07, plan `patentmcp_webdav-r13-refactor`)**:確定性 repo-local 後處理落地為 `skills/patentworks/scripts/*.py`(python3,以使用者 uid 在 host 執行,`--repo`/`--in` 參數,typed JSON 錯誤)。container 收斂為 repoless 網路/憑證閘道。純轉換 SSOT 抽為 `src/patent_mcp_server/_pure/`,skill 帶 vendored `_lib/`(hash drift test 固化)。

## Critical File Index
- `/home/pkcs12/projects/patentmcp/README.md`
- `/home/pkcs12/projects/patentmcp/mcp.json`
- `/home/pkcs12/projects/patentmcp/src/patent_mcp_server/patents.py`
- `/home/pkcs12/projects/patentmcp/src/patent_mcp_server/search_dispatcher.py`
- `/home/pkcs12/projects/patentmcp/src/patent_mcp_server/screening_table.py`(現為 `_pure` re-export shim)
- `/home/pkcs12/projects/patentmcp/src/patent_mcp_server/_pure/`(確定性純轉換 SSOT:screening.py/claims.py)
- `/home/pkcs12/projects/patentmcp/src/patent_mcp_server/_token_store.py`(token store + deliverable-cache class)
- `/home/pkcs12/projects/patentmcp/src/patent_mcp_server/_dav.py`(WebDAV class-2 handler + LockTable)
- `/home/pkcs12/projects/patentmcp/src/patent_mcp_server/_auth_provider.py`(per-owner Basic auth,無 fallback)
- `/home/pkcs12/projects/patentmcp/src/patent_mcp_server/_http_app.py`(HTTP app + /dav 掛載)
- `/home/pkcs12/projects/patentmcp/skills/patentworks/scripts/`(6 支 R13 landing scripts + vendored `_lib/`)
- `/home/pkcs12/projects/patentmcp/skills/patentworks/SKILL.md`
- `/home/pkcs12/projects/patentmcp/skills/patentworks/flows/screening.md`
- `/home/pkcs12/projects/patentmcp/skills/patentworks/flows/priorsearch.md`
- `/home/pkcs12/projects/patentmcp/skills/patent-practitioner-workflow.md`
- `/home/pkcs12/projects/patentmcp/plans/patentmcp_search-dispatcher/`

## Key Architectural Tensions
- **舊 spec vs 現行 README 落差**：舊 `specs/architecture.md` 仍描述 `source/`、`.claude/agents/`、`sample/` 八階段 prompt pipeline，但現行 repo 已重定位為 PatentWorks MCP + skill。
- **分析能力耦合過深**：目前 `screening.md` 內同時描述召回、建表、逐列判讀與可專利性綜述；應切出資料來源無關的 analysis 層，讓使用者提供內容也能直接進分析。
- **交付物 vs 中間產物混用**：screening 的最終交付是 scored CSV，但 drafting 需要的是結構化分析基礎；兩者不應互相假設格式。
- **法遵邊界**：AI 做預篩、分析與起草草稿；人類仍需複核法律裁決。

## Debug / Observability Map
- 檢索工具邊界：`src/patent_mcp_server/patents.py` 的 MCP tool docstring 與返回 schema。
- 統一檢索 dispatcher 邊界(plan `patentmcp_search-dispatcher`, 2026-07):
  - **`src/patent_mcp_server/search_dispatcher.py`**(~400 行):`QuerySpec` dataclass + `normalize_query()`(無檢索軸 → `INVALID_PARAMS` fail-fast,零後端呼叫)、`AXIS_CAPABILITY` 矩陣(各來源支援的查詢軸)、`dispatch_search()` 來源梯:GPSS(官方首選)→ EPO search→biblio 二段(15/min throttle,大 num 截斷記 `biblio_truncated`)→ PPUBS(`uspc` 軸直達、US-only)→ gated gpatents 爬蟲尾級。
  - **Provenance 契約**:每級嘗試一筆 ProvenanceEntry(含 skip 理由/錯誤);單級 error 記錄後續走下一級,不靜默吞。回傳 PatentSearchEnvelope `{success, records[], source, provenance[], gaps[], total, error_code?}`(統一 screening record schema,缺欄誠實留空列入 gaps)。
  - **爬蟲閘**:gpatents 尾級只在 `allow_scraping=True` 執行;官方全 miss 且未授權 → `SCRAPING_REQUIRED` fail-fast(符合天條 §11,與 `fetch_patent_pdf` 同一 gate 語義)。全梯 miss → `ALL_SOURCES_MISS`。
  - **舊工具下架面**:`gpss_search`/`epo_search`/`gpatents_search` 函式本體改名 `_*_impl` 供內部呼叫(`patent_get_claim1`/`fetch_patent_pdf` 等仍用);`uspto_patents` 的 `ppubs_search_patents`/`ppubs_search_applications` methods 拒收並回結構化錯誤指引 `patent_search`。`build_screening_table` 內部改接 dispatcher(對外格式不變,新增 `allow_scraping=False` 參數)。
  - **Deprecation stub 面(2026-07-06, BR_20260706)**:`gpss_search`/`epo_search`/`gpatents_search` 以原簽名重新註冊為 deprecation stub 一個版本週期,呼叫回 typed `{success:false, error_code:"TOOL_RENAMED", use:"patent_search", note}`(比照 `TOOL_LANDED` envelope 慣例),不執行舊邏輯——讓 stale skill 投影/舊劇本第一次呼叫即被糾正而非落 unknown-tool 迴圈。測試:`tests/test_tool_renamed_stubs.py`。改名遷移對照表文件化於 `CHANGELOG.md` 2026-07-06 段。
  - **正規化 adapters**:`screening_table.py` 新增 `ppubs_to_records`、`epo_biblio_to_record`(既有 `gpss_to_records`/`gp_to_records` 之外)。
  - **測試**:`tests/test_search_dispatcher.py`(TV-1~TV-8 + backend-error 續走 + build_screening_table 改接,13 tests;monkeypatch clients 不打真網路)。spec package:`plans/patentmcp_search-dispatcher/`。
- 原始 PDF/圖檔取得邊界（plan `patent-pdf-fetch`, 2026-06）：`fetch_patent_pdf(publication_number, sources?, filename?, include_attempts?)` 統一工具，依序路由 `epo_images`（`EPOClient.images()` + `download_image_pdf()`，EPO OPS 官方影像 API）→ `gpss_pdf`（TIPO 單線程）→ `google_citation`（`GooglePatentsClient.resolve_pdf_url()` 解析專利頁真實雜湊 `citation_pdf_url`）。回 docxmcp 風格 token handle（bytes 不經 model context），token 交 docxmcp `decompose(format=pdf)` 抽圖。端到端實證含 TW 案。文字（claims/全文/圖說）仍走 `google_*` BigQuery + GPSS/USPTO PPUBS。
- 代表圖抓取與降級邊界（plan `remediation_drawing-scraping-cdn`, 2026-06, BR_20260628）：
  - **單線程節流（A）**：所有 GPSS 抓圖工具（`gpss_download_representative_figure` / `_patent_pdf` / `_patent_xml`）共用 module-level `_GPSS_SCRAPE_LOCK`（`patents.py`）序列化（Concurrency=1）+ `_gpss_scrape_pace()` 隨機延遲（env `GPSS_SCRAPE_MIN/MAX_DELAY`，預設 1~3s），防 Cloudflare Managed Challenge。
  - **單一 session 跨全批復用（plan `gpss-session-reuse-batch`, 2026-06）**：`_GpssScrapeSession`（`patents.py`）持有單一持久 `httpx.AsyncClient`，cookie jar（Cloudflare cf_clearance）跨整批累積而非每筆丟棄 —— 修正「每筆新建 client 反而更易觸發 Managed Challenge」的更深層 ReadTimeout RCA。鎖為 **per-burst**（每個 fetch 方法各取 `_GPSS_SCRAPE_LOCK` + pace 後釋放，batch 迴圈本身不持鎖），故非 TW 項經 `extract_representative_figure`→`fetch_patent_pdf`→`gpss_pdf` 再入時不會死鎖於非可重入 lock。兩個 scrape impl（`_gpss_download_representative_figure_impl` / `_patent_pdf_impl`）改吃可選 `session_client`（注入則復用、None 則建拋棄式 client，由 `_gpss_client` asynccontextmanager 控制）；單筆工具行為不變。`patentmcp_batch_download_figures` 修正非 TW 分支 bug（舊碼呼叫 `get_patent()` 取 `representative_figure_url`，但該欄位僅存在於 `search()._flatten()`，導致每筆非 TW 案必失敗）→ 改走報告級 PDF pipeline，不踩被禁的 60x80 縮圖。
  - **CDN 403 降級（B）**：`gpatents_download_figure` 偵測 patentimages 403 → 顯式回 `CDN_FORBIDDEN` + downgrade_hint（不靜默重試）。
  - **代表圖高階工具（D）**：`extract_representative_figure(publication_number, dpi=200)` 用 poppler CLI（`pdfinfo`/`pdftotext`/`pdftoppm`，非 PyMuPDF/AGPL）定位首個 FIG.1 頁（跳封面）→ 高 DPI 渲染 PNG handle；無法定位回 `NO_FIGURE_PAGE`，取代失效的「選最大檔案」策略。
  - **縮圖等級標註（E）**：`GooglePatentsClient._flatten` 對 `representative_figure_url` 加 `representative_figure_resolution: "thumbnail"`；skill 警告縮圖禁用於報告。
  - **EPO 單頁降級（F）**：`fetch_patent_pdf` epo_images 分支以 `_pdf_bytes_page_count`（pdfinfo）偵測頁數 ≤ 1，記 `EPO_BIBLIO_ONLY_1PAGE` 並 continue 下一來源，不落地著錄摘要當代表圖。
  - 跨容器 token 中轉（C，host-pipe SOP）：patentmcp 與 docxmcp 獨立容器/獨立 named volume，token 不互通。**不改 compose**（docxmcp 有 bind-mount ban / AC-01）；改採 host-side pipe：patentmcp blob 端點（TCP `localhost:8000/files/{token}/blob/{rel}`）→ docxmcp 官方攝取入口（`docxmcp_stage_dir` 或 `POST /files` tarball），bytes 不經 model context。SOP 固化於 `skills/patentworks/reference/priorsearch/pdf-figure-extraction.md` §3.4；已實證（50026 bytes PDF 完整搬移）。共用 named volume（方案 B）留待 docxmcp 自身 spec 流程。
- 取文/取圖工具契約強化邊界（plan `br20260628_tooling_skill_gpss_gaps`, 2026-06-28, 三份 BR）：
  - **顯式爬蟲 gate（BR③-A）**：`fetch_patent_pdf(publication_number, ..., allow_scraping=False)`。預設 `allow_scraping=False` 時 `gpss_pdf`（provenance scraping=True）來源被**跳過**（attempts 記 `SKIPPED_SCRAPING_NOT_AUTHORIZED`，不執行抓取）；若官方來源（epo_images/google_citation/local_cache）全 miss 且唯一剩被跳過的 gpss_pdf，回 `SCRAPING_REQUIRED` + hint。**fail-fast 顯式 gate,非靜默 fallback**（符合天條 §11）。內部抓圖呼叫端 `extract_representative_figure` 傳 `allow_scraping=True`；`patentmcp_batch_download_figures` 經前者間接走 gpss,已涵蓋。
  - **參數命名統一（BR③-B）**：取圖/取文工具家族 canonical `publication_number`（單）/ `publication_numbers`（複）;舊名 `patent_number`/`patent_numbers` 保留為 alias(向後相容)。`uspto_patents` 內 `patent_number`（PPUBS patentNumber 語義）不變。
  - **代表圖失敗分級（BR③-C）**：`extract_representative_figure` locate 失敗時用 `_pdf_image_count`（`pdfimages -list`）偵測內嵌影像;image_count>0 回 `NO_FIGURE_PAGE_BUT_IMAGES_PRESENT`（帶 image_count/pages,提示圖在 PDF 內、定位器對無文字層失效）,=0 才維持 `NO_FIGURE_PAGE`。修正掃描版偽陰性。
  - **PPUBS 便利包裝（BR③-D）**：抽出 `_ppubs_resolve_patent_by_number` 共用 pub→guid 解析;`uspto_patents(method="ppubs_get_full_document", publication_number=...)` 無 guid 時自動解析,不需手動串兩段。
  - **GPSS claim1 空旗標（BR①-D）**：`screening_table.gpss_to_records` 用 `_claim1_is_empty`（空字串或剝樣板前綴後無內文）對每筆 record 加 `claim1_empty` 旗標,作為 fallback 到 ③PPUBS 的觸發訊號。
  - **GPSS uspc/family 缺口（BR①-B/C, DD-7）**：無 TIPO GPSS API 官方欄位規格證據,依反幻覺原則**不臆造 uspc 欄位碼**;USPC 軸走 `uspto_patents` PPUBS `CCL/<class>/<subclass>`,family 走 `epo_family`,均落 `patentworks/SKILL.md §5` 文件記載。
  - **skill §5 來源梯窮舉門檻（BR②）**：`patentworks/SKILL.md §5` 新增 Exhaustion Gate（宣告任一欄位缺失前須逐級走完來源梯並留證）、更新工具清單（補載 fetch_patent_pdf/extract_representative_figure/patentmcp_batch_download_figures/ppubs_batch_get_claims,刪除過時「PDF 端點系統性故障」論斷）、重寫爬蟲天條天平（同意後批量軟性機制是正規合規路徑,`scraping:true` 非違規證據）。
  - **工具未 surface（BR①-A, OUT-OF-SCOPE）**：patentmcp 工具未注入 opencode session 工具目錄,屬 opencode `enablement.json`/MCP App 註冊側,非本 repo 可修;待轉 opencode 處理。
- R13 compute/landing split + WebDAV 邊界(plan `patentmcp_webdav-r13-refactor`, 2026-07):
  - **兩平面(R13.5)**:compute plane = container network/credential tools(`patent_search`/`epo_*`/`gpss_download_*`/`fetch_patent_pdf`/`uspto_patents`/`google_*`/`patent_get_claim1`/`ppubs_batch_get_claims`/`pool_fetch`/`cache_*`);landing plane = `skills/patentworks/scripts/`(screening_build/claims_tools/search_audit/figure_extract/pool_charts/patentdb_local)。mcp.json `instructions` 依 R13.5 宣告兩平面分工。
  - **8 個 tool 下架為 typed `TOOL_LANDED` redirect stub**:`build_screening_table`/`stage_file`(script=null,DAV 取代)/`search_audit`/`patentdb_put`/`patentdb_query`/`patentdb_import_csv`/`extract_representative_figure`/`patentmcp_analyze_pool`。保留註冊+schema,回 `{success:false,error_code:TOOL_LANDED,landing:{script,usage}}`,不執行舊邏輯;0.5.0 移除 stub。新增 `pool_fetch`(analyze_pool 取數半段 → records JSON handle)。
  - **純轉換 SSOT**:`_pure/`(stdlib-only,零網路);`screening_table.py` 成 re-export shim;skill vendored `_lib/` 以 `tests/test_vendor_sync.py` sha256 比對防漂移(`PURE_LIB_DRIFT`),`scripts/sync_pure_lib.py` 再生。
  - **WebDAV/cache**:`_token_store.py` deliverable-cache class(class-aware reaper:ephemeral 3600s idle、deliverable-cache dirty 免 reap + safety-net warn-first)+ provision/snapshot_exports/dirty_files/mkdir/move + credential(hmac.compare_digest);`_dav.py` class-2 + LockTable(TTL,衝突 423);`_auth_provider.py` Basic auth 缺/錯 401+WWW-Authenticate、跨 owner 403,**無 identity fallback**(天條 §11);`cache_export` 不可達 target → `EXPORT_TARGET_UNREACHABLE`、`cache_close` dirty → `WORKSPACE_CLOSE_DIRTY`+清單。
  - **測試**:`tests/test_dav.py`/`test_cache_tools.py`/`test_token_store_cache.py`/`test_screening_build.py`/`test_vendor_sync.py`;全套 143 passed(R14 補強後)。spec package:`specs/patentmcp_webdav-r13-refactor/`(已畢業 living)。
  - **rclone 實掛整合驗證(5.5)**:container 8000/tcp 直連 rclone webdav backend,mkdir/rcat/lsf/cat/moveto/copyto/deletefile + 空 collection + 401/403 邊界 12/12 全綠。揪出 4 層 TestClient 漏抓的真 bug 並修復:(a)**PROPFIND rel 尾斜線**→`rel.rstrip("/")`;(b)**空 MKCOL collection 對 PROPFIND 隱形**(`list_files` 僅 rglob is_file)+ Depth:1 誤回遞迴樹→新增 `TokenStore.stat_entry`/`list_dir` 檔案系統感知 primitive,`_propfind` 改寫為 Depth:0/1 直接子節點;(c)**gateway prefix 烤進 base_href/Destination**→改由實際 request path 推導 base_href、mount_prefix 用裸 `/dav`(prefix-agnostic),修正 direct/gateway 雙呼叫者的 href 對不上(lsf 空)與合法同 token MOVE 誤判 cross_token 403;(d)**COPY 未列入 DAV_METHODS**→rclone copyto 405 →新增 `_copy` handler(同 subject COPY,保留源,Overwrite 頭支援)。回填 3 個 unit regression test。
- Skill routing：`skills/patentworks/SKILL.md` 的 flow 選擇表。
- 檢索/分析領域規格：`skills/patent-practitioner-workflow.md`。
- Flow 契約：`skills/patentworks/flows/*.md`。
- MCP 啟動設定：`.mcp.json`。
- 成品樣本：`output/**/*.csv`。

## Plan-Builder Spec Package
- Active plan root: `specs/20260320_repo-planner-specs-plan/`。
- Core artifacts: `proposal.md`、`spec.md`、`design.md`、`tasks.md`、`handoff.md`、`implementation-spec.md`。
- 本 package 成功定義了 `analysis` 作為資料來源無關的中介層與輸入輸出契約（已於 2026-06-26 完整實作 `flows/analysis.md` 與前後銜接路由）。

## Architecture Sync Note
- 2026-06-15: 已將架構 SSOT 從舊八階段 prompt pipeline 重構為 PatentWorks MCP + skill 現況；新增 analysis 作為資料來源無關的 planned boundary。
- 2026-06-26: 獨立分析技能流程 `skills/patentworks/flows/analysis.md` 實作完成，並已同步更新 `SKILL.md` 路由表，以及 `screening.md` 與 `drafting.md` 的銜接說明。
- 2026-07-03: 單一檢索入口上線(plan `patentmcp_search-dispatcher`)。新增 `search_dispatcher.py` + `patent_search` tool;`gpss_search`/`epo_search`/`gpatents_search`/`uspto_patents` search methods 下架;`build_screening_table` 改接 dispatcher;mcp.json 0.3.0;README/skill 文件同步。Critical File Index 舊 `PatentDrafter`/`vendor/patents-mcp` 失效路徑同步修正為現行 repo 佈局。詳見 Debug/Observability Map dispatcher 段。
- 2026-07-03: R13 compute/landing split + WebDAV working cache 上線(plan `patentmcp_webdav-r13-refactor`,依 `opencode/specs/mcp-integration-standard` §R13)。新增 `_pure/`(純轉換 SSOT)+ `skills/patentworks/scripts/` 6 支 landing scripts + vendored `_lib/`;8 個確定性 tool 下架為 `TOOL_LANDED` redirect,新增 `pool_fetch`;`_token_store.py` 加 deliverable-cache class;新 `_dav.py`(class-2 WebDAV)+ `_auth_provider.py`(per-owner Basic auth,無 fallback)+ 4 個 `cache_*` lifecycle tools;mcp.json 0.4.0 + R13.5 兩平面 instructions;SKILL.md/screening.md/README 同步。134 tests 全過。Module Boundaries 新增「本地計算層」與 WebDAV 交付層;Critical File Index 補新模組。詳見 Debug/Observability Map R13 段。
- 2026-07-06: R14 fleet conformance 補強(BR_20260706,對映 opencode plan `mcp_webdav-fleet-conformance` tasks §3)。R14.6:`cache_provision` 新增 opt-in `issue_webdav_credential` flag(mint-or-rotate、cleartext 僅回一次、default payload byte-identical,port 自 docxmcp reference commit `54eac2e`);R14.4:確認 `_safe_target` 已覆蓋 PUT/DELETE/PROPFIND/MKCOL/MOVE/COPY 全 DAV 路徑,回填 4 個 traversal 拒絕 regression tests;R14.5:compose 註明 builtin auth provider 即 per-host provisioning(patentmcp 無 gateway-backed 變體,無需 env switch);R14.7:stage-inline 已由 DAV PUT + `/files/{token}/blob/{rel}` UDS GET 取代(`stage_file` TOOL_LANDED 明示轉導,loud 非 silent)。mcp.json instructions 同步 R14.6 用法。全套 143 tests 綠。
- 2026-06-28: 處理三份 BR(plan `br20260628_tooling_skill_gpss_gaps`)。`patents.py` + `screening_table.py` 工具層強化(顯式爬蟲 gate / 參數命名統一 + alias / 代表圖失敗分級 / PPUBS 便利包裝 / GPSS claim1_empty 旗標,20 tests 全過);`patentworks/SKILL.md §5` 加來源梯窮舉門檻 + 工具清單更新 + 爬蟲天條天平重寫。BR①-A(工具未 surface)判定為 opencode side、非本 repo 範圍。詳見 Debug/Observability Map 對應段落。
