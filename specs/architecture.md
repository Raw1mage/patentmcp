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
  - **單一檢索入口(2026-07, plan `patentmcp_search-dispatcher`)**:`patent_search` 是唯一 SEARCH 工具;來源梯(GPSS→EPO→PPUBS→gated gpatents)內建於 `search_dispatcher.py`,呼叫者不選來源。舊分散檢索工具(`gpss_search`/`epo_search`/`gpatents_search`/`uspto_patents` 的 `ppubs_search_*`)已下架;單號取文工具保留。**EPO 分支布林 keyword(2026-07-10, plan `patentmcp_bulk-entry-unification`)**:keyword 經 `_keyword_to_cql`(`search_dispatcher.py`)轉逐 term 帶欄位前綴的 CQL(`radar AND fall`→`txt=radar and txt=fall`,引號片語保留單 term,括號/NOT 透傳),修正舊「整串當片語」導致布林檢索全掛的 bug;測試 `tests/test_keyword_to_cql.py`。
  - **單一批次入口(2026-07-10, plan `patentmcp_bulk-entry-unification`)**:`patent_bulk(source="gpss"|"epo", ...)` 是唯一窮盡批次工具,source 必填顯式選源(無預設、無跨源 fallback,缺/非法→`INVALID_PARAMS` 零後端呼叫)。dispatcher 層 `bulk()` 只做路由:gpss 依 keyword 有無內部二路(無→`bulk_export` 分類軸全拉;有→`bulk_harvest` 收割),epo→`epo_bulk_harvest`(per-page absorb:每頁 biblio fan-out 完成即落地 patentdb,client 逾時不丟已落地頁;OPS skip wall ~2000)。envelope 統一超集含 `next_skip`/`exhausted` 續撈語義(GPSS 側於路由層補算)。舊三工具 `patent_bulk_export`/`patent_bulk_harvest`/`epo_bulk_harvest` → `TOOL_RENAMED` stub(`use:"patent_bulk"`,一個 release cycle)。測試 `tests/test_patent_bulk.py`。**EPO auto date-slicing(同 plan Phase 7,DD-8/DD-9)**:`patent_bulk(source="epo", slice_plan=true)` planning-only 呼叫 → `epo_slice_plan`(`search_dispatcher.py`)count-probe(num=1 零 biblio fan-out)取母數;>wall(2000)且有 date 範圍 → 遞迴二分 date 區間(互斥切點,深度 cap 6 / probe cap 32,觸頂片標 `truncated`)至每片 <wall;sum_check 5% 容忍守恆自證(超過 → `SLICE_INEFFECTIVE` fail-fast)、無 date 範圍 → `DATE_RANGE_REQUIRED`。呼叫者逐片呼叫 + 片內 `next_skip` 續撈(拒絕 server 單呼叫逐片全拉——BR1 timeout 根因)。非 planning EPO 呼叫 total>wall 且未 exhausted 時 envelope 補 `slice_hint` 提示。測試 `tests/test_epo_slice_plan.py`。**GPSS auto query-slicing(2026-07-15, DD-10/DD-11, BR_20260715)**:GPSS keyword harvest 撞 `GPSS_ERROR: Exceeded search condition length` 時,`bulk_harvest`(`search_dispatcher.py`)自動分片、對呼叫端透明回單一 union。POST 已實測封死(GPSS 後端只讀 URL query string,body 忽略——對照探測 B==A空請求 且 C==D userCode-not-exist),故分片是唯一解(同時解 URL 414 + condition length 兩道牆)。分片為確定性集合論運算:`_parse_gpss_query`/`_shard_gpss_query` 只二分詞數最多的**正向** AND-of-OR 群,**NOT 群每 shard byte-identical 完整保留**(`(Bx∪By)∩C¬D=(Bx∩C¬D)∪(By∩C¬D)` 分配律成立,但 `¬(D1∪D2)=¬D1∩¬D2≠¬D1∪¬D2`,拆 NOT 群靜默漏排),遞迴二分深度 cap 6,pubno union 去重,envelope 補 `sharding:{applied,shards[{query_frag,total,landed}],union_total,union_landed}`;不可再分(單詞+全 AND/NOT 仍超長)→ `CONDITION_LENGTH_IRREDUCIBLE` fail-fast。閘值 `_GPSS_CONDITION_LENGTH_LIMIT=900`(TIPO 上限不透明,保守估) + shard 實擈仍撞牆則 fail-fast(belt-and-suspenders)。測試 `tests/test_gpss_query_slice.py`。**號碼軸顯化 + fail-loud(2026-07-18, plan `patentmcp_patent-bulk-number-axis-fail-loud`, BR_20260718)**:`patent_bulk`/`patent_search` 的 `pub_number` 參數升級為單值或清單皆收(`Optional[Union[str,List[str]]]`,清單內部 join 成 GPSS `no or no` PN 形式,單值向後相容),顯化 number-list 匯出入口,呼叫者不必知道 `keyword+keyword_field=PN` 隱式用法;`patent_bulk` 新增 `pub_number`(原本缺)。`normalize_query`(單一收斂點)偵測 keyword 內 GPSS **web-進階-檢索專用**的號碼軸語法(`@PN`/`@AN`/`@PD` 尾綴 + 整包外括號)——這類語法在 GPSS **keyword 引擎**會被當全文靜默 miss(同族 BR_20260709 教訓的同構),故預設清洗(strip 尾綴 + 拆外括號,記 provenance `number_axis_cleaned`),清洗後仍非合法號碼列 → typed `NUMBER_AXIS_SYNTAX_UNSUPPORTED` fail-loud(絕不靜默 zero_hits);一般全文 keyword 不誤判。`_run_gpss` zero_hits 分級:PN 軸/已清洗/疑似號碼語法 → note `likely_number_syntax_error` + 自救 hint。測試 `tests/test_number_axis_failloud.py`。**GPSS REST 截斷體重試 + transport 語義分流(2026-07-18, BR_20260718)**:常駐行程的 `GPSSClient.search`(`gpss/client.py`)在 Cloudflare 掐斷 keep-alive 半死連線後仍間歇收到截斷 body(既有 disable-keep-alive fix 不完全),`_parse_gpss_json` 三層 sanitize 針對格式畸形、救不回截斷 → 舊碼回裸 `Expected JSON but parse failed`,曾被下游(DD-53)誤定性為「引擎無英文召回能力」。修復:parse 失敗時先用**一次性短命 client**(`GPSSClient._fresh_get`;短命連線實測從不復現截斷)重打同 URL `_TRUNCATION_RETRIES=2` 次;仍失敗 → typed `{error_code:"GPSS_TRUNCATED_BODY", transport:"truncation", raw[:500]}` fail-loud,error 文案明示 TRANSPORT failure、禁止當 zero_hits/無召回能力解讀——`parse failed`(連線層)≠`zero_hits`(能力層)自此在 error_code 層分流。測試 `tests/test_br20260718_fixes.py`。
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
- **GPSS4 會員區 web-app 層 (`gpss4/`, 2026-07-11, plan `patentmcp_gpss4-folder-tools`)**
  - 驅動 TIPO GPSS4 **web app 登入會員區**(專案資料夾/標記清單),與 `patent_search` 的 REST 檢索梯**完全不同**:session-based(自訂 `TTS*` cookie)、5-GIF CAPTCHA 登入、token-URL 導覽。
  - **登入契約(DD-2/3/4,實測)**:GPSS4 用 **URL 帶 session slot**——每次 GET 首頁 `gpssbkm?@@<rand>` mint 新 slot(ID 遞增),CAPTCHA 答案綁那個 slot。整條登入鏈必須騎同一 slot(抓首頁一次→登入頁 parse hidden `ID`/`SECU`/`TPHC` + 5 張 glyph gif url→抓圖→md5 對照表 OCR→POST→跟進 SSO meta-refresh)。CAPTCHA glyph 是靜態字模(同字元跨 session md5 固定),`CaptchaTable`(`ocr.py` + `captcha_data/md5_table.json`,35 glyph)查表辨識,棄用圖像 OCR/模板比對。認證訊號用 SSO 落地頁會員標記(登出/專案/資料夾),**非** `TTSUID` cookie(成功時仍空)。
  - **標記寫入契約(DD-5,實測)**:三步 server-side session 序列——號碼檢索 POST(`_21_1_T=(<no>)@PN` image submit)→ `clickselect` AJAX GET(`gpssbkm?<TOK>^S^<db>_<rec>_<curt>_1^`,把勾選寫進 server session,裸 POST checkbox 會被判「請勾選資料」)→ POST `BUTTON=加入標記清單`。**加入標記 POST 的回應頁即標記清單**(同步 HTML 表格)。陷阱:home 頁 `gpssbkm?.<token>` 標記清單連結綁過期 slot,回空殼(固定「無標記資料」佔位)。
  - MCP tools:`gpss4_folder_search`(號碼檢索,唯讀)/`gpss4_folder_mark`(加入標記,寫入)/`gpss4_folder_list`(列標記清單)。憑證來自 `GPSS4_USERNAME`/`GPSS4_PASSWORD`(env/.env)。
  - **進階檢索 scraper(`adv_search.py`,DD-7..DD-11,實測 2026-07-11)**:繞過 GPSS API 每日下載配額——驅動登入態 web 進階檢索 harvest 帶 **family 分組**的結果列表(專案資料夾 export 缺 family 已 CLOSED,故改此路)。
    - **純 httpx,無瀏覽器(DD-13,de-browsered 2026-07-11;取代 DD-8)**:早期 DD-8 誤判「只有瀏覽器能傳短命 slot key」。PoC 證明 httpx 可從每頁 HTML **抽出** slot key 帶到下一請求(就像瀏覽器),整條進階檢索是純 HTTP 狀態機,playwright+chromium 移除。login 已純 httpx(session.py);「進階檢索」**tab anchor**(`gpsskm?.<hex>`,`class=link`)從 member.html(`_refresh_chain`)抽,非右側進階檢索設定區塊(落 `_20_*` 環境頁無 `_3_10_X`)。
    - **流程(全 httpx GET/POST)**:GET tab → POST `_3_10_X`=檢索式 + INFO + `_IMG_檢索.x/.y` → 回應直接是結果列表(<50 筆)或 job shell(`NeedCheck=1`+`ptmp=kmwork/N` → 輪詢 `ttsserv_watch?<kmtmp>/km.swp:4:1:全部:` 到 `DB_OK`)→ POST `BUTTON=家族收合` → 翻頁 → 抽 row。**關鍵 parse**:GPSS 原始 HTML `<tr>/<td>` 不閉合(35 開 vs 16 閉),須以 `<tr` 開標籤 `re.split` 切割,不可用 `<tr>...</tr>` 貪婪配對(會一列吞 18 筆)。query 語法用官方欄位代碼(`(詞)@TI`/`@AB`/`@CL`/`CS=xxx`/`AD=y1:y2`,非 `TI=(x)`)。
    - **CLI 入口(DD-14)**:`python -m patent_mcp_server.gpss4.adv_search "<query>" --csv pool.csv [--max-pages N] [--no-family]`;首字 `@`+檔名 → 從檔讀 query;standalone 自載 repo root `.env`(上 3 層)。
    - **family 綁定鍵(DD-10,成敗關鍵)**:家族收合頁序號欄 `N.M`(家族 N 成員 M)即 per-patent 家族鍵——静態 HTML 直接給,不需 `web_familyjob` AJAX 展開。**修正早期誤判**:`clickselect(this,db,rec,group)` 的 group 是逐筆選取序號(1..18 無共享),**非**家族鍵。GPSS 只給「簡易專利家族」分組,無 INPADOC 標準編號字串。
    - **分頁(DD-11,兩機制;httpx 化)**:簡目頁=頁碼 `<select>` 預算好的短命 slot-URL(GET);家族收合頁無 select,改 JPAGE 跳頁 POST(`BUTTON=顯示結果`+`JPAGE=N`)。每頁 **50 筆為進階檢索上限**(「每頁」選單只有 10/20/30/40/50,無 100 選項;option value 是 slot-key URL 非 pagesize 欄位)。slot URL 短命——逐頁即時抽不可預拼。
    - **完整翻頁 + 截斷訊號(2026-07-11)**:harvest 邊翻頁邊 parse 每頁 row 累積成單一完整 pool(同 API 分頁抓取本質)。`max_pages` 預設 **200**(≈一萬筆安全上限,非批次大小);真達上限但未翻完 → 回傳 `truncated=true`+`complete=false`,**不靜默截斷**(舊版預設 20 會静默丟弃大結果集。實測 `(set-top box)@TI`=11009 筆/221 頁,舊版只給 60 筆不告知)。
    - **zero-hit 監測器壳辨識(2026-07-18, BR_20260718)**:零命中檢索 server **永遠不渲染結果列表**,query POST 只回**檢索表單監測器壳**(`chkURL` 契約,len≈30k,「前次檢索還沒好」)——與結果頁的 `AURL` job shell 不同契約。舊碼誤讀為「簡詳目並列 view switch failed」(曾被下游誤判為引擎 bug)。修復:`_submit_query` 無 result markers 時輪詢 `_search_ready_watch`(chkURL 衛星 `ttsserv_watch?<kmtmp>/km.swp:<slot>:1:全部:` 到 `DB_OK`,parse per-DB 命中數 `全部(N)`);`全部(0)` → `GPSS4AdvZeroHits` → `harvest()` 回結構化空池 `{total:0, hit_count:0, zero_hits:true, db_counts, patents:[]}`;DB_OK 但 hits>0 無列表 → typed fail-loud。活體驗證:BR 兩失敗分片(B2b×C-β/γ 同構 query)實為真 zero-hit,非引擎卡住。測試 `tests/test_br20260718_fixes.py`。
    - MCP tool:`gpss4_advanced_search(query, max_pages, expand_family, delivery, owner_identity, subject_id, csv_rel, csv_path)` → `{total, family_count, representative_count, summary_family_count, patents[](seq/pat_no/apply_date/title/abstract/family_group/is_family_representative), + 交付 handle}`。實測 known-good query(純 httpx,host+容器 import 均通,容器重啟後 /tools 列出,總 46 tools):24 筆 / 15 distinct 家族 / 2頁 / abstract 24/24,與舊 playwright 版一致。claims 需詳目頁(未作)。
    - **交付管道(`delivery` 參數,接上 patentmcp 標準 file rails,與其他 artifact 工具一致)**:`token`(預設)→ CSV bytes 走 `token_store.put_bytes()`+`_handle()`,回 `{token, rel, download_url, sha256}`,經 `/files/{token}/blob/{rel}` 下載(docxmcp 相容);`cache`→ 需 `owner_identity`+`subject_id`(天條§11 never infer),land 進 WebDAV deliverable-cache(`/dav/<subject>/<csv_rel>`,回 `mount_path`+首次 `credential`,之後 `cache_export` 到 truth-store);`none`→ 只回 JSON。`csv_path` 為 legacy escape hatch(向後相容)。實測:token blob GET HTTP 200 拿回 32KB UTF-8-BOM CSV;cache 發 credential;缺 owner_identity → `OWNER_REQUIRED` fail-fast。
    - **部署**:GPSS4 web 會員憑證 `GPSS4_USERNAME`/`GPSS4_PASSWORD`(有別於 REST API 的 `GPSS_USER_CODES`)須 docker-compose.yml environment 列出(已補)+ `.env` 填值。compose environment 變更須 `docker compose up -d` 重建容器(`docker restart` 不重讀定義);純 code 變更靠 `./src` bind mount 熱掛,只需 restart 重掃工具。
    - **家族去重(DD-12,非破壞性)**:`annotate_family_representatives` 純函式不刪任何筆,每筆加 `is_family_representative`—同家族最早 apply_date 者為代表(pat_no 破 tie),`family_group=None` 視為自身單筆家族。去重 = filter 該 flag(可逆)。GPSS 家族號全域連續(非 per-page 重置),`family_count`(收合後實際 distinct)== 代表數,與 `summary_family_count`(收合前估計)可不同,以前者為準。
  - **number-query 改走 adv 路徑 + 登入模式互斥閘(plan `patentmcp_gpss4-number-query-adv-route`, 2026-07-19, BR_20260719 §4/§4A)**:
    - **根因(recon 坐實,推翻 BR §4「scope+欄位」假設)**:folder 標記清單結果頁**不 render 專利號**(`gpss4_folder.search_number` 有 hits 但 `MarkList._extract_rows` 抽 0 筆公開公告號),導致 `gpss4_resolve_appnos` 對 pending_tw_99 resolved 率掉到 0。真解=改走 `adv_search` 的**簡詳目並列**檢視(`_enter_dual_view`,唯一 render 專利號的檢視面)。
    - **`adv_search.resolve_one(s, number, axis, country)`(DD-3)**:單號解析,復用既有 adv primitives(`_submit_query`→`家族收合`→`_enter_dual_view`→`AdvResultPage.parse`),只取第一頁 dual-view 第一筆匹配 row(單號查詢僅一家族,不做全軸分頁 harvest)。axis:`apply`→@AN / `pub`→@PN。匹配用去前綴零數字比對。
    - **per-session DB scope 前置(DD-4)**:`GPSS4Session._scope_set`(login 時清空)記錄本 session 已設 DB codes;`adv_search._ensure_query_ready(s, country)` 依國別(`_COUNTRY_TO_DBS`:TW/CN/US/JP/KR/EP → 公開庫+公告庫)推導,`_scope_set` 未含所需才 `set_search_databases` 並記入 —— **per-session 設一次(非每查重設)**。粒度決策定案:§4A gate 消除並發 → 同 session 內 config 不可能被別人改 → 設一次即確定性安全(非 BR §4.2 反對的猜 config latch,並發已被 gate 物理消除)。scope 設定失敗 raise `GPSS4DbScopeError`(fail-fast,絕不用可能錯的現有 scope 續查回假 unmatched)。
    - **§4A 互斥 + 跨呼叫 keep-alive SSOT(`gpss4/session_manager.py`, plan `patentmcp_gpss4-session-keepalive`, 2026-07-19)**:登入模式**禁並發、禁雙登入**(TIPO 帳號節流鎖定血淚硬規則,曾因多 session 並存把帳號打進鎖定)。舊 `login_gate.py`(per-call acquire/release + 呼叫結束 `s.close()`)只解並發,不解**跨呼叫重登**——每個 MCP 呼叫各開/關一 session、各登入一次,仍燒登入額度。**新架構(使用者拍板 3 決策)**:MCP process 內維護 module-level 單一 `_SessionManager`(SSOT,DD-1),治理**至多一個** live authed `GPSS4Session`,跨呼叫復用。**兩個生命週期解耦(核心 DD-3)**:`in-use 期`(一次呼叫,仍 §4A 互斥 fail-fast)vs `session 存活期`(跨呼叫 keep-alive,mint→reap 橫跨多次 in-use)。`acquire(holder)`=reuse-or-mint(DD-2):有 live+健康+未逾 TTL → 復用**不重登**;已有 in-use holder → 立即 raise `GPSS4LoginBusyError`(帶現持有者+held_for+真進程 exe `readlink /proc/self/exe`,承接舊 gate DD-7,**純旗標 fail-fast** 非 `asyncio.Lock`,不排隊/不重試/不開第二 session);無/逾 TTL/不健康 → close 舊 + mint 新登入一次。`release(holder)`=**keep-alive(DD-4,不 close)**,只標 idle + 更新 last-used,session 留 SSOT 供下次復用;真 close 僅由顯式 `gpss4_session_close` 或 reaper 觸發(雙保險)。**TTL<90min(DD-5)**:idle TTL(env `GPSS4_SESSION_IDLE_TTL_SEC`,default 600s)+ absolute TTL(`GPSS4_SESSION_ABSOLUTE_TTL_SEC`,default 3600s,< TIPO 實測 ~90min slot 死線),lazy-on-acquire 檢查逾期即回收。**復用前健康檢查(DD-2/6,無 fallback)**:`_healthy()` 走 `session.get`(本身帶 redirect-to-login 偵測)打輕量 member 頁,非 authed/例外即 False → close+mint,絕不靜默續用可能失效 session。`live session 恆 0 或 1`,天條由「至多一 live + 至多一 in-use」雙不變式守住。用法:`async with shared_session("<holder>") as s`,release keep-alive 保證在 `__aexit__`(含例外路徑)。**GPSS REST 路徑不入 SessionManager**(官方金鑰、配額制、不碰登入面,不同認證平面,DD-7 邊界)。**`login_gate.py` 已標 deprecated shim**(互斥語義完全併入 SessionManager,無 caller 殘留)。
    - **4 個登入模式進入點全套改接 SessionManager(`patents.py`)**:`gpss4_resolve_appnos`(改走 resolve_one + `shared_session` 借還,移除自建 `GPSS4Session()`+`finally: close()`;batch 全程單一共享 session,scope 設一次,回 `effective_scope` 可觀測)+ `gpss4_folder_list`/`gpss4_folder_mark`/`gpss4_folder_search`(注入共享 session 給 `GPSS4Folder(session=s)`,**不呼叫 f.close()** 避免誤關共享 session,release 由 context manager keep-alive)。並發回 `GPSS4_LOGIN_BUSY` typed error(契約相容)。**新增 2 tool**:`gpss4_session_close`(顯式歸還,回 `{closed, was_busy}`)+ `gpss4_session_status`(可觀測:live/busy/holder/age/idle/expires_in/`login_count`——keep-alive 成功=login_count ≪ 呼叫數)。測試 `tests/test_gpss4_session_keepalive.py`(11 tests:reuse不重登/mint/並發fail-fast/release keep-alive/idle+absolute TTL/health-fail重建/顯式close/close-while-busy/finally例外歸還/release mismatch;mock login計數+mock時鐘),全套 gpss4 27 passed 零回歸。spec package:`plans/patentmcp_gpss4-session-keepalive/`。
    - **batch slot 契約(2026-07-19 live 驗證 + instrumented trace 坐實)**:GPSS4 slot anchor(`gpsskm?.<hex>` 進階檢索 tab)是 **session 級「當前 slot」指標**——每個 HTTP response mint 新 slot 並作廢前一個(非 per-query token)。故 batch 多筆必須 **anchor-chaining**:`resolve_one` 首查用 login-cached member anchor(`_extract_adv_tab_url`),之後用上一筆 harvest 的 anchor(存 `GPSS4Session._adv_tab_next`,login 清空)。**harvest 時機是 root cause**:必須在該筆**最後一個 response**(dual-view 後,`_harvest_next_anchor(dual_html, result_html)`)才抓——早抓(submit 後)會被隨後的 dual-view POST 作廢 → 下一筆 spent anchor → `len=289`。單號查詢 `_enter_dual_view(bump_page_size=False)` 省掉 pagesize GET(結果 <50 筆用不到),減少 slot-advancing 請求。
    - **connection-refused transient retry(2026-07-19)**:大結果集項之後,下一筆的任一 HTTP hop(adv-form GET / query POST / 家族收合 POST / dual-view POST)偶回 ~289-byte TTS stub「SystemMessage:Connection refused.」——**連線層 transient**(TCP 被拒,請求從未到 app 層,anchor 未消耗,**非**配額/登入逾時)。`_is_transient(html)` predicate(marker 或 body<600)+ `_post_retry` helper(escalating backoff 重試同一請求,safe by TCP-reject semantics;`_ADV_FORM_RETRIES=4`/`_ADV_FORM_BACKOFF=1.5`)套到 adv-form GET + 三個 POST 落點。live 全 appno batch **6/6 resolved 0 error**(前為 2/N 硬停)。
    - **設定頁 read-modify-write(2026-07-19)**:`set_search_databases` POST 是**整頁存檔**——未 echo 的 checkbox 存成未勾。原碼只 echo `_20_1_S_*`(資料庫)+ hidden,漏掉輸出欄位 → fresh account 靜默失去公開公告號輸出。修:read-modify-write 保全全部 checkbox/radio + `_REQUIRED_OUTPUT_FIELDS`(`_20_20_S_*` 簡目 / `_20_23_S_*` 詳目 的 PN/AN/TI/日期)force-ensure。設定頁三區塊逆工:`_20_1_S_*`=資料庫、`_20_20_S_*`/`_20_23_S_*`=輸出欄位(後綴=欄位碼)、`_20_6_A`/`_20_14_A`=顯示格式 radio。
    - **測試**:`tests/test_br20260719_adv_route.py`(10 tests:gate 互斥/finally release/例外 release/序列重取;country map;scope 設一次復用/跨國擴充/未知國 fail-fast 不觸 settings)。**live 驗證(2026-07-19)**:pending_tw_99 全 appno 切片 `gpss4_resolve_appnos` **6/6 resolved**(前為 0);known-item TW roundtrip `TW109112770→TW202138759A`(對齊 converter ground truth)。**Remaining**:CN/US 跨國各一筆 live 驗,deferred 待 GPSS4 登入額度窗口(帳號鎖定風險)。spec package:`plans/patentmcp_gpss4-number-query-adv-route/`。
- **GPSS3 網頁路徑布林檢索計數 (`gpss_web_search`, 2026-07-16, plan `patentmcp_gpss-web-boolean-search`)**
  - 驅動 gpss3 **人類登入路徑**做布林檢索**計數**(各庫命中數 + 結果列書目),**零 API 額度**——與 `patent_search` 的 GPSS REST 梯(`gpss_client.search`,燒 quota)完全不同平面。用於「要 GPSS 完整布林力(欄位化括號/NOT/鄰近/切截)但不想耗 REST 配額」或無 `GPSS_USER_CODE` 時。
  - **核心洞察(沙盤推演+真實網路雙證)**:單一欄位化括號布林式(如 `(radar or mmwave)@TI not (vehicle)@AB`)整串塞進**單一檢索欄位** `_21_1_T`,gpss3 接受並執行——不需拆分欄表單。欄位限定靠字串內 `@TI`/`@AB` 語法(非表單分欄),日期靠 `ID=YYYYMMDD:YYYYMMDD` 併入檢索式,國別走 `patDB` POST 參數(**現況未真正限縮,見 issue_20260716**)。
  - **複用既有 gpss3 handshake 基礎設施**(`patents.py`):`_gpss_client` / `_GPSS_POLICY.guard` 節流 / `_gpss_extract_info` INFO token / `_gpss_extract_action` action URL / `_gpss_iter_result_rows` 結果列解析——不重造。
  - **AJAX 各庫筆數(t7 探明)**:精確命中數非同步載入,端點 `/gpss3/gpsskmc/ttsserv_watch?<kmtmp>/km.swp:102:1:全部:`,`kmtmp` 源自結果頁 `ptmp` 前綴,回應由 `transferULLI` 解析 `subdbname(rec)` 各庫命中數;`_gpss_web_search_impl` 輪詢至各庫就緒(max `poll_max`,逾時→`GPSS_WEB_POLL_TIMEOUT` 回部分就緒 + `pending_databases`)。
  - **fail-fast 天條(無 fallback)**:語法非法(`_gpss_web_validate_expr` 欄位代碼白名單 + 括號配對)→`INVALID_PARAMS` **零網路呼叫**;INFO 抽取失敗→`GPSS_WEB_HANDSHAKE_FAILED`;母數 >30萬→`GPSS_WEB_RESULT_TOO_BROAD` + 限縮提示(不回 records)。全路徑**絕不** fallback 到 `gpss_client.search` REST(省額度)。
  - **防呆修正(code-thinker 咒語#3)**:`_gpss_web_is_too_broad` 第一版把頁面固定 furniture(`class=reclock` 重新計時按鈕 + `close_nodup` 去重停用 tooltip「超過30萬筆」)誤判成母數上限→正常查詢誤回 TOO_BROAD。修正:真溢出訊號 = 母數哨兵 **AND 無 `ptmp`**(真溢出無法產生結果暫存 key;正常大母數頁仍有 ptmp 該輪詢)。
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
- `/home/pkcs12/projects/patentmcp/src/patent_mcp_server/_resources.py`(R17.1(c) portable floor:token-store artifact ↔ `patent://{token}/{rel}` resources/list+read)
- `/home/pkcs12/projects/patentmcp/src/patent_mcp_server/_capabilities.py`(R17.1.1 結構化 capability summary,endpoint visibility=container|host-visible)
- `/home/pkcs12/projects/patentmcp/src/patent_mcp_server/_delivery.py`(R17.2.4/5 typed asset preflight + content assertions,cache_export delivery gate)
- `/home/pkcs12/projects/patentmcp/src/patent_mcp_server/_dav.py`(WebDAV class-2 handler + LockTable)
- `/home/pkcs12/projects/patentmcp/src/patent_mcp_server/_auth_provider.py`(per-owner Basic auth,無 fallback)
- `/home/pkcs12/projects/patentmcp/src/patent_mcp_server/_http_app.py`(HTTP app + /dav 掛載)
- `/home/pkcs12/projects/patentmcp/skills/patentworks/scripts/`(6 支 R13 landing scripts + vendored `_lib/`)
- `/home/pkcs12/projects/patentmcp/skills/patentworks/SKILL.md`
- `/home/pkcs12/projects/patentmcp/skills/patentworks/flows/screening.md`
- `/home/pkcs12/projects/patentmcp/skills/patentworks/flows/priorsearch.md`
- `/home/pkcs12/projects/patentmcp/skills/patent-practitioner-workflow.md`
- `/home/pkcs12/projects/patentmcp/plans/patentmcp_search-dispatcher/`
- `/home/pkcs12/projects/patentmcp/src/patent_mcp_server/gpss4/`(GPSS4 會員區:session.py 登入/ocr.py CaptchaTable/folder.py 標記清單)
- `/home/pkcs12/projects/patentmcp/plans/patentmcp_gpss4-folder-tools/`

## Container Lifecycle / Compose Project 邊界

patentmcp 以**單一 per-user compose project** 承載。三個檔案共同定義這條邊界，改任一個都必須三處同步：

| 檔案 | 角色 |
| --- | --- |
| `docker-compose.yml` | 頂層 `name: patentmcp-${USER:-nouser}` = **預設 project 名**；`container_name: patentmcp` = 全域唯一容器名 |
| `webctl.sh` | 唯一正規生命週期入口（`start`/`stop`/`restart`/`refresh`/`health`/`clean`/`purge`），一律帶 `-p "patentmcp-${USER:-$(id -un)}"` |
| `scripts/patentmcp-self-heal.sh` | `--check`/`--heal` 探測與復原，必須算出**與 webctl 相同**的 project 名 |
| `scripts/_compose_lib.sh` | **上兩者共同 source 的單一來源**：`PROJECT` / `CONTAINER` / `assert_no_project_drift()` 都定義在這裡 |

**為何 `container_name` 是全域的，且刻意保留**：它把容器名釘死成跨所有 compose project 唯一。代價是「不同 project、同一容器名」必然撞牆；效益是這個撞牆**很大聲**——沒有這行的話，兩個 project 會各自生出 `<project>-patentmcp-1`，變成**靜默跑出兩份服務**，症狀難察覺得多。這是刻意選擇的失敗形狀：寧可吵，不要靜默分裂。

**漂移是怎麼發生的（BR_20260730，實際發生過 8 天）**：一次省略 `-p` 的裸 `docker compose up` 會讓 compose 以**目錄名**為 project（`patentmcp`），而 webctl 一律驅動 `patentmcp-${USER}`。此後容器歸屬舊 project、webctl 找不到它，`restart` 每次都在 recreate 階段死於 daemon 的 name conflict——而那則錯誤訊息**從不提及 compose project**，讀起來像殘留容器問題，不像它實際上的歸屬漂移。

**兩道防線**（缺一不可，職責不同）：

1. **結構防線** `docker-compose.yml` 的頂層 `name:` —— 消除**根因**。有了它，即使裸 `docker compose up`（無 `-p`）也會落在正確 project，不再退回目錄名。`-p` 仍可覆蓋，所以 webctl / self-heal 保有完全控制權。
   - 用 `:-nouser` 而非 `:?`：interpolation **即使 `-p` 已覆蓋此鍵仍會求值**，所以 `:?` 守衛會讓**正確路徑**（systemd unit / cron 下 `USER` 未設的 `webctl.sh start`）直接失敗。2026-07-30 於 compose v5.3.1 實測：`-p explicit` + 未設 `USER` + `:?` → `required variable USER is missing a value`, exit 1。純預設值不會 fail；若 `USER` 真的未設，webctl 自己的 `id -un` fallback 會與之分歧，並由下面第 2 道防線大聲報出。
2. **行為防線** `scripts/_compose_lib.sh::assert_no_project_drift()` —— 攔截**已經發生**的漂移。偵測到同名容器屬別的 project 就 fail fast（exit 1，唯讀不動服務），印出實際歸屬、本腳本驅動的 project、修復指令，以及「被遺棄的 project 仍持有 sessions volume」的警告。呼叫點涵蓋**所有會 mutate 的路徑**：`webctl.sh` 的 `start` 與 `restart`、`patentmcp-self-heal.sh` 的 `heal`。在 `restart` 路徑它刻意排在 build **之前**——衝突會讓 recreate 必敗，先花數分鐘 build 只是延後同一個錯誤。
   - **為何抽成共用 lib（2026-07-30 VANS 覆核）**：guard 原本私有於 `webctl.sh`，而 self-heal 算出**同樣的** project 名、驅動**同樣的** `docker compose up`，卻完全繞過它——`--heal` 因此仍會撞上那則不提 compose project 的 daemon 衝突，也就是 guard 存在的理由本身。修法刻意**不複製一份** guard 到 self-heal：兩個 caller 各持一套規則自由漂移，與 `_skill_shipping.py` 的 list/download 分歧是同一個缺陷形狀（見「Skill Shipping」段），而那正是同一張 BR 在 Python 側剛修掉的東西。
   - **測試錨點** `tests/test_compose_drift_guard.py`：以 PATH 上的 docker stub 驅動真正的 lib，釘住三個分支的**決策**（自有放行且靜默／容器不存在放行／漂移拒絕）與**拒絕的可診斷性**（訊息須指名 owner、印修復指令、警告 volume），另有結構斷言禁止私有重定義、並釘住 guard 必須排在 `up` **之前**。在此之前 guard 完全沒有自動化測試，只能靠操作者實際跑 verb 才會發現回歸——正是原始漂移潛伏 8 天的同一個盲區。

**volume 歸屬的連帶效應**：project 名決定 named volume 前綴（`<project>_patentmcp-sessions`），所以切 project = 換 token store。判斷「舊 volume 能不能丟」必須**實際打開看內容**，不能從掛載關係推論——BR_20260730 的初判就是這樣寫反的（推論「沒掛的那顆是空的」，實際相反：漂移前它才是現役那顆）。

## Key Architectural Tensions

- **舊 spec vs 現行 README 落差**：舊 `specs/architecture.md` 仍描述 `source/`、`.claude/agents/`、`sample/` 八階段 prompt pipeline，但現行 repo 已重定位為 PatentWorks MCP + skill。
- **分析能力耦合過深**：目前 `screening.md` 內同時描述召回、建表、逐列判讀與可專利性綜述；應切出資料來源無關的 analysis 層，讓使用者提供內容也能直接進分析。
- **交付物 vs 中間產物混用**：screening 的最終交付是 scored CSV，但 drafting 需要的是結構化分析基礎；兩者不應互相假設格式。
- **法遵邊界**：AI 做預篩、分析與起草草稿；人類仍需複核法律裁決。

## Debug / Observability Map

- **Unified observability log 邊界(plan `observability_tool-friction-log`, 2026-07-15)**:patentmcp 的**統一**觀測記錄機制——工具層 error、靜默磨擦、HTTP 存取全進**同一 store、同一 record API、同一查詢面**。
  - **`src/patent_mcp_server/friction_log.py`**(模組名保留相容,語義已升級為 unified):SQLite store 單表 `events`,`category` 欄區分 `friction`(kind=exception|silent)與 `access`(kind=http);共用欄 `ts/category/kind/tool/reason/detail`,friction 專屬 `source/args_summary`,access 專屬 W3C 語義 `method/uri/status/duration_ms/client_ip/user_agent/mcp_client`。統一底層寫入 `record_event(...)`,薄包裝 `record_friction(kind,...)`(向後相容)/ `record_access(...)`。全部 fail-open(任何錯誤只 warn 吞掉,絕不 raise——觀測不得成為故障源)。落點 `/patentdb/observability.sqlite`(寄生現有 `./patentdb` bind-mount,rebuild 存活,WAL)。
  - **中央 exception choke point(DD-1)**:`patents.py` import 區塊末以 monkeypatch 把 `mcp.tool` 替換為 `friction_tool(_orig_mcp_tool)`——所有 ~48 個 `@mcp.tool()` 工具透明經 wrapper 註冊,未捕捉 exception 記 `category="friction" kind="exception"` 後原樣 re-raise。**必須先捕獲 `_orig_mcp_tool` 原始 bound method**(否則 wrapper 內呼叫已被覆蓋的 `mcp.tool` → 無限遞迴)。`functools.wraps` 保留 signature,FastMCP schema 內省不受影響(實測 `patent_search` 參數 schema 完好、48 工具全註冊)。
  - **HTTP access log(DD-6/DD-7)**:`_http_app.py` build_app 尾端以**純 ASGI middleware**(`_access_log_mw`)包住已掛完路由的 Starlette app,每個進來的 HTTP 請求落一筆 `category="access"` row(W3C 語義)。**必須在所有 `app.router.routes.extend` 之後才包**(太早包會把 Starlette app 換成無 `.router` 的裸 ASGI callable → build_app 掛路由時 AttributeError)。純 ASGI(非 BaseHTTPMiddleware)故 SSE/streaming 不受影響——只 peek response-start 狀態碼,不 buffer body。實測辨識出來客 `mcp_client: opencode`。
  - **靜默磨擦顯式埋點(DD-2)**:`logger.warning(...)+continue` 型磨擦(非 exception,無法自動辨識)由呼叫端顯式 `record_friction(kind="silent", ...)`。首批熱點:patent_search 的 patentdb absorb 失敗(`patents.py` ~3198)。可增量補 source ladder miss / EPO throttle / SCRAPING_REQUIRED。
  - **觀測方式**:無 MCP 查詢工具(使用者決策)——開發時直接讀 `patentdb/observability.sqlite`。範例:磨擦排名 `SELECT kind,tool,source,reason,count(*) FROM events WHERE category='friction' GROUP BY 1,2,3,4`;來客存取 `SELECT datetime(ts,'unixepoch','localtime'),method,uri,status,duration_ms,mcp_client FROM events WHERE category='access' ORDER BY id DESC`。憑證絕不入 log(`_SECRET_KEYS` 剔除 + args 只存短摘要 + URI query 剝除)。
  - spec package:`plans/observability_tool-friction-log/`。
- 檢索工具邊界：`src/patent_mcp_server/patents.py` 的 MCP tool docstring 與返回 schema。
- 統一檢索 dispatcher 邊界(plan `patentmcp_search-dispatcher`, 2026-07):
  - **`src/patent_mcp_server/search_dispatcher.py`**(~400 行):`QuerySpec` dataclass + `normalize_query()`(無檢索軸 → `INVALID_PARAMS` fail-fast,零後端呼叫)、`AXIS_CAPABILITY` 矩陣(各來源支援的查詢軸)、`dispatch_search()` 來源梯:GPSS(官方首選)→ EPO search→biblio 二段(15/min throttle,大 num 截斷記 `biblio_truncated`)→ PPUBS(`uspc` 軸直達、US-only)→ gated gpatents 爬蟲尾級。
  - **Provenance 契約**:每級嘗試一筆 ProvenanceEntry(含 skip 理由/錯誤);單級 error 記錄後續走下一級,不靜默吞。回傳 PatentSearchEnvelope `{success, records[], source, provenance[], gaps[], total, error_code?}`(統一 screening record schema,缺欄誠實留空列入 gaps)。
  - **爬蟲閘**:gpatents 尾級只在 `allow_scraping=True` 執行;官方全 miss 且未授權 → `SCRAPING_REQUIRED` fail-fast(符合天條 §11,與 `fetch_patent_pdf` 同一 gate 語義)。全梯 miss → `ALL_SOURCES_MISS`。
  - **舊工具下架面**:`gpss_search`/`epo_search`/`gpatents_search` 函式本體改名 `_*_impl` 供內部呼叫(`patent_get_claim1`/`fetch_patent_pdf` 等仍用);`uspto_patents` 的 `ppubs_search_patents`/`ppubs_search_applications` methods 拒收並回結構化錯誤指引 `patent_search`。`build_screening_table` 內部改接 dispatcher(對外格式不變,新增 `allow_scraping=False` 參數)。
  - **Deprecation stub 面(2026-07-06, BR_20260706)**:`gpss_search`/`epo_search`/`gpatents_search` 以原簽名重新註冊為 deprecation stub 一個版本週期,呼叫回 typed `{success:false, error_code:"TOOL_RENAMED", use:"patent_search", note}`(比照 `TOOL_LANDED` envelope 慣例),不執行舊邏輯——讓 stale skill 投影/舊劇本第一次呼叫即被糾正而非落 unknown-tool 迴圈。測試:`tests/test_tool_renamed_stubs.py`。改名遷移對照表文件化於 `CHANGELOG.md` 2026-07-06 段。
  - **正規化 adapters**:`screening_table.py` 新增 `ppubs_to_records`、`epo_biblio_to_record`(既有 `gpss_to_records`/`gp_to_records` 之外)。
  - **測試**:`tests/test_search_dispatcher.py`(TV-1~TV-8 + backend-error 續走 + build_screening_table 改接,13 tests;monkeypatch clients 不打真網路)。spec package:`plans/patentmcp_search-dispatcher/`。
- 跨 DB 號碼格式 converter SSOT 邊界(plan `patentmcp_cross-db-pubno-converter`, 2026-07-19, BR_20260719):
  - **`src/patent_mcp_server/pubno_convert.py`**(純函式,僅 stdlib `re`):跨資料源號碼格式**唯一真實來源**。同一件專利在不同 DB 需不同格式,過去格式邏輯散落 ≥5 處各自臨場處理 → 假 miss/假 not_found 反覆發生 + 消費端盲試變體燒 token。收斂為單一 layer。函式:`to_patentdb_key`(patentdb PK = 現 canonical_pubno,CN/TW 剝 kind、US 留數字 kind)/`patentdb_key_variants`(對帳雙 key `[stripped, original]`,消 §2.4 kind-strip 假缺口)/`to_gpss_rest`(完整 pubno)/`to_gpss4_web(raw,axis=None)`(去國碼數字 + 號形推斷軸別:`TW\d{9}` 民國年→apply/@AN,否則 pub/@PN,消 TW 申請號誤走 @PN)/`to_epo_variants`(EPO docdb,US pre-grant 序號 10↔11 位雙變體,主形式在前)/`to_docdb`(docdb primary form)。
  - **variants-first,非 silent fallback**(DD-2,天條 §11):歧義號型回 list(主形式在前),呼叫端逐個顯式 fallback;無法解析回空 list/None,絕不猜測號。
  - **收斂面(5 處改走本 layer,刪重複邏輯)**:`epo/client.py`(`to_docdb`/`docdb_variants` → converter thin re-export,保留既有 import 路徑)、`patentdb_store.py`(`canonical_pubno`/`normalize_pubno` 委派;`_KNOWN_CC` 保留供 patents.py import)、`patents.py`(`_get_patent_country_and_normalized_no` 委派)、`scripts/family_backfill_offline.py`(host-local script 注入 sys.path 改用 canonical `to_docdb`,取回舊簡化版缺的 US 變體能力)、`skills/patentworks/scripts/patentdb_local.py`(host landing plane,R13.6 no-import-from-src,以 **vendor 複製 + 同步註記** 維持一致)。
  - **DD-1 vendor-drift guard**:pytest 以 AST 語句序列比對 `patentdb_local.normalize_pubno` 與 `pubno_convert.normalize_pubno` 逐字相同,drift 即 fail —— 把「vendor 複製」人工紀律升為機檢閘。
  - **DD-3 向後相容硬閘**:`to_patentdb_key` 對所有既有輸入逐字等同收斂前 `canonical_pubno`(回歸測試把關;既有 `test_patentdb_store.py` 11 tests 全綠)。
  - **測試**:`tests/test_pubno_convert.py`(mapping 向量 TV-1~8 + 5 處收斂 import + vendor-drift guard + 向後相容回歸,19 tests)。**Remaining**:實查 roundtrip 抽樣(EPO US pre-grant/TW @AN)deferred 待額度窗口。spec package:`plans/patentmcp_cross-db-pubno-converter/`。
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

- 2026-07-21: R17 minimum operational toolset + host mediation 上線(plan `patentmcp_r17-minimum-operational-toolset`,依 `opencode/specs/mcp-integration-standard` §R17)。三 gap 補齊(既有 R17.1(a/b)/R17.4/R17.5 已達標之上):**R17.1(c) portable floor**——新 `_resources.py` + FastMCP 註冊,每個 token-store 產物經 `resources/read` @ `patent://{token}/{rel}` 協定原生取得(免 host socket/WebDAV),`resources/list` 動態 mirror live token store(`_resource_manager.list_resources` 覆蓋);unknown token/rel 與 traversal 逃逸 fail-loud、絕不空讀。**R17.1.1 結構化 capability summary**——`patentmcp_init` 由 prose-only 加寬為 `{doctrine, capabilities}`,每個 endpoint 標 `visibility=container|host-visible`(container UDS socket 不被誤認 host-executable);`prompts/get` 維持 prose-only,doctrine 兩 face byte-identical(`_capabilities.py`)。**R17.2.4/5 typed asset preflight**——`_delivery.py` + `cache_export` 接線:空工作樹 `EXPORT_EMPTY` 拒交付(nothing lands),optional content assertions(`assert_min_files`/`assert_nonempty`/`assert_contains_rel`)fail-loud `ASSERTION_FAILED`。**R17.6 eval**——`tests/test_r17_conformance.py` 端到端雙跑(portable-floor `resources/read` 無 WebDAV / WebDAV `cache_export`+assertions 空拒);mcp.json 0.5.0→0.6.0 + R17 signpost;全套 361 tests 綠。Critical File Index 補三新模組。
- 2026-07-19: patentdb 擁有權對齊上線(issue_20260706 F1)。容器以 root 跑(compose 無 `user:`)、`_save_local_patent_cache` 容器側 mkdir/write 產 root-owned 案目錄,host 側 landing scripts(figure_extract.py 等)寫回撞 EACCES。修法:`patentdb_store.py` 新增 `align_db_ownership()`(僅 euid=0 生效;以 bind-mount root(`/patentdb`)的 stat uid/gid 為對齊目標;fail-open 絕不阻斷寫入路徑),`patents.py _save_local_patent_cache` 三寫入點(案目錄/figures/metadata.json)接線。存量 255 個 root-owned 檔/目錄已一次 `chown -R 1000:1000` 修復。容器內功能實測:新建案目錄+檔案落地後 uid=1000。附註:`friction.sqlite`/`observability.sqlite` 為容器側 lazy-init,新建仍可能 root-owned,但僅容器讀寫、不影響 host 落地路徑。
- 2026-06-15: 已將架構 SSOT 從舊八階段 prompt pipeline 重構為 PatentWorks MCP + skill 現況；新增 analysis 作為資料來源無關的 planned boundary。
- 2026-06-26: 獨立分析技能流程 `skills/patentworks/flows/analysis.md` 實作完成，並已同步更新 `SKILL.md` 路由表，以及 `screening.md` 與 `drafting.md` 的銜接說明。
- 2026-07-03: 單一檢索入口上線(plan `patentmcp_search-dispatcher`)。新增 `search_dispatcher.py` + `patent_search` tool;`gpss_search`/`epo_search`/`gpatents_search`/`uspto_patents` search methods 下架;`build_screening_table` 改接 dispatcher;mcp.json 0.3.0;README/skill 文件同步。Critical File Index 舊 `PatentDrafter`/`vendor/patents-mcp` 失效路徑同步修正為現行 repo 佈局。詳見 Debug/Observability Map dispatcher 段。
- 2026-07-03: R13 compute/landing split + WebDAV working cache 上線(plan `patentmcp_webdav-r13-refactor`,依 `opencode/specs/mcp-integration-standard` §R13)。新增 `_pure/`(純轉換 SSOT)+ `skills/patentworks/scripts/` 6 支 landing scripts + vendored `_lib/`;8 個確定性 tool 下架為 `TOOL_LANDED` redirect,新增 `pool_fetch`;`_token_store.py` 加 deliverable-cache class;新 `_dav.py`(class-2 WebDAV)+ `_auth_provider.py`(per-owner Basic auth,無 fallback)+ 4 個 `cache_*` lifecycle tools;mcp.json 0.4.0 + R13.5 兩平面 instructions;SKILL.md/screening.md/README 同步。134 tests 全過。Module Boundaries 新增「本地計算層」與 WebDAV 交付層;Critical File Index 補新模組。詳見 Debug/Observability Map R13 段。
- 2026-07-11: R16 domain-KB self-shipping 上線(plan `mcp_r16-domain-kb`,依 `opencode/specs/mcp-integration-standard` §R16)。新增 `patentmcp_kb_query`/`patentmcp_kb_get`(read-only in-band serving of `.specbase/ragbase.sqlite`;FTS/LIKE/hybrid 查詢規劃 + matchMode 自述;`KB_UNAVAILABLE` fail-fast envelope);compose 掛載 `./.specbase:/var/lib/patentmcp/kb`(rw 僅為 WAL side files,唯讀由 `mode=ro`+`query_only` 連線層強制)+ `PATENTS_KB_DB` env;mcp.json 0.5.0 + recall-first signpost;SKILL.md 增 recall-first 段;5 個判斷密集工具加 `consider:` affordance。KB 寫入唯一路徑仍是 host-side specbase `producer.ts`(one KB two doors,R16.7)。tool surface 36→38;12 新測試 + 全套 199 綠;TV-6 兩門一致性通過。
- 2026-07-07: R15 self-describing guide 上線(plan `mcp_r15-self-describing-guide`,依 `opencode/specs/mcp-integration-standard` §R15)。新增 `patentmcp_init` MCP tool(`readOnlyHint/idempotentHint=true`, `openWorldHint=false`)+ **新建** `prompts/list`+`prompts/get patentmcp_init` handler(FastMCP `@mcp.prompt`);兩 face 共用 `patents.py:_guide_doctrine()` 投影 `skills/patentworks/SKILL.md`(one-source,啟動缺檔/空檔 `RuntimeError` fail-fast,天條 §11),live smoke 實測 tool==prompt body byte-identical(13595 chars,R15.5 no-drift)。`mcp.json.instructions` + server instructions 各補 R15.3 signpost。usage doctrine 自此以 delivered context 在 action boundary 就地遞送,不再仰賴 host-side prose 被模型主動記憶。tool surface 由 35→36。
- 2026-07-06: R14 fleet conformance 補強(BR_20260706,對映 opencode plan `mcp_webdav-fleet-conformance` tasks §3)。R14.6:`cache_provision` 新增 opt-in `issue_webdav_credential` flag(mint-or-rotate、cleartext 僅回一次、default payload byte-identical,port 自 docxmcp reference commit `54eac2e`);R14.4:確認 `_safe_target` 已覆蓋 PUT/DELETE/PROPFIND/MKCOL/MOVE/COPY 全 DAV 路徑,回填 4 個 traversal 拒絕 regression tests;R14.5:compose 註明 builtin auth provider 即 per-host provisioning(patentmcp 無 gateway-backed 變體,無需 env switch);R14.7:stage-inline 已由 DAV PUT + `/files/{token}/blob/{rel}` UDS GET 取代(`stage_file` TOOL_LANDED 明示轉導,loud 非 silent)。mcp.json instructions 同步 R14.6 用法。全套 143 tests 綠。
- 2026-07-15: 對外公開 HTTP 多傳輸面上線(plan `patentmcp_public-http-faces`)。`_http_app.py` 擴充：tool schema 分頁(`/tools` HTML 索引 + `/tools/{name}` 遞迴 inputSchema、JSON 移至 `/tools.json`)、landing tool rows 連結化、`/webdav/{subject}` 別名指向同一 `dav()` handler(base_href 由實際 request path 推導)、`/sse` 自建 `SseServerTransport`(`/sse` 用 Route 避 Mount 307、`/sse/messages` 用 Mount，**不** mount `sse_app()` 以避 streamable session-manager lifespan 雙重進入，DD-5)。gateway web route 經 ctl.sock publish `/patentmcp uds .run/patentmcp.sock auth=0` 公開。e2e 經 `https://cms.thesmart.cc/patentmcp/` 實測：landing/tools.json/tools/{name}/sse/mcp 全公開直通；`/dav/{subject}` 公開直通 app(app-level 401 Basic auth)。**已知限制**：`/webdav/{subject}` 別名經 gateway 穩定回 login page(gateway 對 `/patentmcp/webdav/*` 前綴套 login 牆，binary 層行為、非本 repo route config 可改)→ 對外公開 WebDAV 一律用 `/dav/{subject}`，`/webdav` 僅供已認證 gateway session。
- 2026-06-28: 處理三份 BR(plan `br20260628_tooling_skill_gpss_gaps`)。`patents.py` + `screening_table.py` 工具層強化(顯式爬蟲 gate / 參數命名統一 + alias / 代表圖失敗分級 / PPUBS 便利包裝 / GPSS claim1_empty 旗標,20 tests 全過);`patentworks/SKILL.md §5` 加來源梯窮舉門檻 + 工具清單更新 + 爬蟲天條天平重寫。BR①-A(工具未 surface)判定為 opencode side、非本 repo 範圍。詳見 Debug/Observability Map 對應段落。
