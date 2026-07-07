---
name: patentworks
description: 專利全流程工作站。四種任務:(A) 把發明材料/idea 整理成技術交底書;(B) 前案/現況檢索 → 產出已評分、可稽核的人類可讀表格;(C) 針對給定技術想法進行前案檢索、102/103比對與差異分析並產出撰寫基礎;(D) 從技術揭露起草符合各國法規的專利說明書(請求項+說明書+摘要)。當使用者要「整理交底書/挖專利點」「找前案/查有沒有人做過/技術現況」「前案比對與技術特徵分析」或「寫專利說明書/起草專利申請」時使用。檢索重 US/CN;起草分 共通/TW/CN/US/EP 五法域。
---

# PatentWorks

> **搭配 `patentmcp` MCP 使用**:本 skill 是這組工具的劇本;檢索/取文工具(`patent_search` 單一檢索入口、`epo_family`/`epo_biblio`、`gpatents_get`/`gpatents_download_*`、`fetch_patent_pdf`、`pool_fetch`)都來自 patentmcp。沒有該 MCP 時本 skill 無法執行實際檢索。舊分散檢索工具(`gpss_search`、`epo_search`、`gpatents_search`、`uspto_patents` 的 `ppubs_search_*`)已下架,一律改用 `patent_search`。
>
> **Companion skill `patentworks` — 動手前先載入(point-of-decision)。** 你現在讀到的這份文本,可能是透過 `patentmcp_init` 工具/`prompts/get` 在動作邊界收到的**可攜 in-band 濃縮本**;本 skill 才是完整劇本(五法域起草規則、flow 檔、資料樹規範、法遵自檢)。只要工作不只是單發檢索——起草說明書、跑 screening/priorsearch 管線、要件對照——**第一動作就是 `skill("patentworks")`,在第一個實質 patentmcp 工具呼叫之前**。tool-chain idiom(選 flow、選來源梯判讀、交付契約)住在 skill 裡,per-tool `description` 裝不下;在決策當下載入才擋得掉「自己選檢索來源、自己拼 OOXML/CSV」的反射。**這是 advisory,不是 gate**:純 MCP 客戶端(無 skill 機制)光憑這份 doctrine 直接呼叫工具仍屬正確——guide 對上述紀律自足,skill 加深度、非前置條件,不破壞協議可攜性。
>
> **兩平面(R13):container 只留網路/憑證工作,確定性後處理落地為 host-local skill 腳本。** 以下 8 個舊工具現回 typed `TOOL_LANDED` redirect(不再執行舊邏輯,`landing.usage` 直接給對應腳本呼叫式),請改呼叫 `skills/patentworks/scripts/` 下的本地腳本(每支 `python3 <腳本> --help` 印完整參數):
>
> | 舊工具(已下架 → TOOL_LANDED)                          | 改用本地腳本                                                                            |
> | ----------------------------------------------------- | --------------------------------------------------------------------------------------- |
> | `build_screening_table`                               | `screening_build.py`(records JSON → 家族去重 → 欄位隨選 → CSV)                          |
> | `search_audit`                                        | `search_audit.py`(`--log 01_search/matrix-log.jsonl`)                                   |
> | `patentdb_put`/`patentdb_query`/`patentdb_import_csv` | `patentdb_local.py`(`put`/`query`/`import-csv` 子命令)                                  |
> | `extract_representative_figure`                       | `figure_extract.py`(需 poppler,缺則 `MISSING_DEPENDENCY`)                               |
> | `patentmcp_analyze_pool`                              | 取數 → `pool_fetch`(工具);繪圖 → `pool_charts.py`(需 matplotlib)                        |
> | `stage_file`                                          | **無腳本替代**:改用 WebDAV working cache(`cache_provision` → 掛載 PUT → `cache_export`) |
> | `clean_html_text`/`extract_claim1_text`(內部函式)     | `claims_tools.py`(`clean-html`/`extract-claim1`/`claim1-empty`)                         |
>
> **WebDAV working cache(交付物暫存三層心智)**:`cache` = 可拋的工作樹(mount 掛載處);`truth store`(專案 repo / `output/`)= 交付物的家;**export 是顯式動作**,不 export 就不算落地。流程:`cache_provision(subject_id, owner_identity)` 拿到 `mount_path` + **一次性 Basic 憑證**(只存 hash)→ 用 rclone/davfs2 掛載後**投料/取件走 mount**(byte 不過 context)→ 成品就緒 `cache_export(subject_id, target, owner_identity)` COPY 落地(target parent 不存在 → `EXPORT_TARGET_UNREACHABLE`)→ `cache_close`(有未 export 的 dirty 檔 → `WORKSPACE_CLOSE_DIRTY` 擋下,列未落地清單,除非 `force=True`)。DAV 面強制認證,無 fallback。憑證絕不寫進報告/log。
>
> **憑證自助 bootstrap(R14.6,fleet 標準,docxmcp reference commit 54eac2e)**:首次 `cache_provision` 就回一次性 `credential`;憑證遺失或要重建 mount 時,`cache_provision(subject_id, owner_identity, issue_webdav_credential=True)` 走 MCP-rail 重發——**持有 MCP socket 本身就是授權**,免掉 HTTP 先有雞先有蛋。**警告:此旗標會 ROTATE 憑證,任何用舊密碼的現存 mount 立即失效**,只在建立/重建 host mount 時帶。不帶(預設 false)時 payload 與舊行為 byte-identical(天條 §11 無 silent 欄位)。
>
> **anti-reflex 鐵律(寫在手上)**:檔案坐落在 gdrive / 網路 FUSE 掛載,**永遠不是** WebDAV working cache 不可用的理由——這是**兩軸混淆**的經典 category error。Location(`.md`/圖檔坐落哪個檔案系統)與 Transfer(bytes 怎麼過 host↔container 邊界)是**正交**的;只按 Transfer 軸路由。WebDAV 這條走 pass-by-value(bytes 過 DAV wire,容器不需看見任何 host path);它在本 host 不通,真因是 **credential / mount 未 provision**(見 `issues/` webdav-provision BR),與 gdrive/FUSE 無關。有疑慮時,`cache_provision` + mount 這條 pass-by-value 到處都能用;大檔只是多付 context/傳輸成本。

專利從 idea 到申請的全流程。依需求選一個 flow,**先讀對應 flow 檔再執行**。

## 完整管線

```
disclosure(交底書)→ screening(查新)→ analysis(分析)→ drafting(起草說明書)
發明材料/idea ──────────────────────────────────────────→ 專利申請文件
```

四者可單獨用,也可串成完整旅程;前一段的產出是後一段的輸入。

## 選 flow

| 使用者意圖                                                                  | flow                       |
| --------------------------------------------------------------------------- | -------------------------- |
| 整理交底書 / 從專案材料挖專利點 / 發明揭露                                  | **`flows/disclosure.md`**  |
| 有沒有人做過 / 找前案 / 可專利性 / 技術現況 / landscape(輕量,出 scored CSV) | **`flows/screening.md`**   |
| 跨美陸台前案地圖 / 收斂到 N 件 / 要正式 Excel 池 + 技術洞察報告 DOCX        | **`flows/priorsearch.md`** |
| 前案檢索與可專利性比對(102/103) / 做要件對照表(Claim Chart) / 製作起草基礎  | **`flows/analysis.md`**    |
| 幫我寫專利說明書 / 請求項 / 起草申請                                        | **`flows/drafting.md`**    |

> screening 內部又分「可專利性(要件對照→新穎性綜述)」與「landscape(主題分群→技術地圖)」——細節見該 flow。
> **screening vs priorsearch**:screening 出一張 scored CSV(輕量查新);priorsearch 是 landscape 的重型交付版——建立**固化工作資料夾**(中間產物 + 交付物分層、`04_report/` 結構與 docxmcp package 調和)、跨三地官方 API、收斂件數、產出含逐字 Claim 1 與**檢索方法復現章**的 Excel + DOCX 正式報告。要正式報告走 priorsearch。

## 共用原則(兩 flow 皆適用)

1. **交付物是人類可讀的成品**(screening = scored CSV;drafting = 說明書文件),一律經 patentmcp `stage_file` / docxmcp token+blob handle 交付,bytes 不過 context。
2. **法域意識**:檢索預設 US/CN(TW 低價值);起草須先定目標法域,載入 `reference/drafting/common.md` + 對應法域檔。
3. **法遵以 skill 知識處理,不做工具**:合規/法條要點寫在 `reference/drafting/{common,tw,cn,us,ep}.md`,起草時逐條自檢。
4. **AI 做預篩/起草草稿 + 解釋,人類複核裁決**(專利有法律份量)。
5. **來源優先序——已內建於 `patent_search`,官方梯優先、爬蟲尾級需授權**:檢索一律呼叫單一入口 `patent_search`(參數:`cpc/ipc/uspc/keyword/keyword_field/applicant/inventor_country/pub_number/date_from/date_to/databases/num/skip/allow_scraping`)。**你不選來源**——server 依憑證可用性與查詢軸能力沿來源梯(①GPSS → ②EPO → ③PPUBS → gated 爬蟲)自動路由,每級嘗試記入回傳的 `provenance[]` 供稽核;回傳 `{success, records[], source, provenance[], gaps[], total, patentdb_absorb}`(缺欄誠實留空並列入 `gaps`)。**每次命中即自動吸收進全域 patentdb**(2026-07-06):成功的 records 當場 upsert 進 `patentdb.sqlite`,`patentdb_absorb: {imported, updated, skipped}` 供稽核,吸收失敗不阻斷檢索。檢索矩陣跑完池即已入庫,**不需收尾手動 `patentdb_import_csv` 回填**(回填僅用於歷史 CSV 救援)。爬蟲尾級只在 `allow_scraping=True`(使用者明確授權)才跑;官方全 miss 且未授權 → `error_code=SCRAPING_REQUIRED` fail-fast(其餘錯誤碼:`INVALID_PARAMS` 無檢索軸、`ALL_SOURCES_MISS`)。以下各級條目是**各來源能力/限制的領域知識**(判讀 provenance、單號取文選工具時用),不是要你手動選檢索來源:
   - **📦 分類軸窮盡批次匯出用 `patent_bulk_export`(coverage,非 relevance)**:當需求是「把某個分類軸(IPC/CPC/USPC)底下的**完整書目一次全拉下**」(如 AIOT 全景擴充、專利地景窮盡取數),用 `patent_bulk_export(ipc=.../cpc=.../uspc=..., databases=[...], num=數千)`,**不要**用 `patent_search`。兩者語義正交:`patent_search` 找「最相關的幾件」(keyword AND 收窄、num≈30、官方 miss 退爬蟲);`patent_bulk_export` 拉「整條軸」(**純分類軸、不吃 keyword**避免過度收窄、大 num 自動分頁 expSkip、強制全欄 expFld 杜絕半殘 row)。**GPSS-only、官方 miss 即真 0 絕不退爬蟲**(無 `SCRAPING_REQUIRED`);records 經 COALESCE upsert 入 patentdb,可重跑回補既有半殘 row(如 `title_en` 空白)而不覆寫。回 `{success, records[], source:"gpss", provenance[], gaps[], total, patentdb_absorb}`;錯誤碼 `INVALID_PARAMS`(無分類軸)/ `GPSS_NOT_CONFIGURED` / `GPSS_ERROR`。
   - **⛳ 來源梯窮舉門檻(Exhaustion Gate)——硬規則**:**在報告中宣告任一資料欄位(逐字 Claim 1 / 代表圖 / 全文 / 書目)「從缺 / 無解」之前,必須沿下方來源梯逐級走完,並在報告「誠實缺口」章為每一級留下實測結果(成功 / 失敗 + 失敗原因)。** 只在第①級回空就停手 = **流程缺陷,不是合法降級**。對應 `search_audit`「先驗過程再驗產物」的精神——同一套窮舉思維延伸到「取文/取圖強度」。常見漏走的下一級: - **Claim 1 回空** → 走 ③`uspto_patents`(US 案最可靠,實證 `ppubs_batch_get_claims` 一次可補完整逐字 Claim 1);觸發訊號:`patent_search` / `build_screening_table` 的 records 帶 `claim1_empty: true`(GPSS 級回應另附 `claim1_audit{empty_count, empty_pubnos[]}`,工具層直接給,列出需補抓的公開號)。- **代表圖缺** → 先 `fetch_patent_pdf`(官方路由優先),圖通常**就在已下載的 PDF 裡**;`extract_representative_figure` 對掃描版回 `NO_FIGURE_PAGE_BUT_IMAGES_PRESENT`(帶 `image_count`)時,代表「圖在 PDF 內、只是定位器對無文字層失效」,應從已下載 PDF 抽圖,**不是宣告無圖**。- **某工具回空 / 某定位器失敗 ≠ 整件事終局無解**;一律換工具 / 走下一級 / 從已在手的中間產物再加工。- **🔴 委派契約(Delegation Gate)——把 Exhaustion Gate 強制寫進子代理 task prompt(BR_20260628 復發修復,2026-07-06)**:**子代理不讀本 skill、不讀 AGENTS.md**——取圖/取文的窮舉義務**只能靠 orchestrator 的 task prompt 傳遞**。因此凡委派取文/取圖/前案吸收類子代理,task prompt **必須明文帶上**以下條款(缺這段 = 委派缺陷,子代理必重演「未走取圖梯就宣告從缺」)。**以下 `<!-- delegation-clauses -->` 區塊由 opencode runtime 於本 skill pinned 時自動注入委派子代理的 prompt(BR_20260706),不再靠主代理手抄;手抄仍是無 runtime 注入時的 fallback**:
     <!-- delegation-clauses -->
     **專利取文/取圖窮舉契約(Exhaustion Gate)——委派子代理 MUST 遵守**:
6. **代表圖從缺前必走雙路徑**:TW/CN 案先 `patent_search(pub_number=...)` 走 GPSS headless 直接取圖;US/WO/EP 案 `fetch_patent_pdf`(官方路由優先)→ 圖通常就在下載回的 PDF 內 → `extract_representative_figure` / 從 PDF 抽圖。**兩路徑都實測失敗、且在報告留下每案每級實測結果,才可宣告「無圖」。**
7. **逐字 Claim 1 從缺前必走 PPUBS**:US 案 `claim1_empty:true` → `ppubs_batch_get_claims` 補抓,補不到才可宣告從缺。
8. **回報格式**:子代理須回「每案取得狀態 + 走過哪幾級 + 各級成功/失敗原因」,**不接受一句「官方來源圖式從缺」的終局結論**。工作區 PDF count=0 / figure count=0 而宣稱「已窮舉」= 未執行,退回重跑。
9. **爬蟲授權沿用主代理**:子代理不得自行決定啟用爬蟲;`allow_scraping` 由 orchestrator 依使用者授權在 task prompt 指定。
   <!-- /delegation-clauses -->
   - **① GPSS(首選級)**——TIPO 官方 REST,一次回 PN/AN/標題/摘要/Claim1/CPC/IPC/申請人/日期,IPC 錨定,一站涵蓋 US/CN/TW。逐字 Claim 1 用 `patent_search(pub_number=...)` 單號查詢三地通用(底層仍 GPSS 首選)。**已知限制(`patent_search` 走 GPSS 級時)**:(a) **US 案 Claim 1 偶為空**(只回 "What is claimed is:" 無內文)——records 會帶 `claim1_empty: true`,須走 ③PPUBS 補抓;(b) **不提供 INPADOC 家族 ID**,去重僅到「公開號級」,要家族級 collapse 走 ②`epo_family`;(c) **無 USPC 軸**——GPSS 級只有 `cpc`/`ipc`;給 `patent_search(uspc="705/300")` 時 dispatcher 會**直達 ③PPUBS**(US-only 軸);(d) **TW 案書目欄位偶為空**(標題/申請人空欄但案件存在,非查無此案)——以 `epo_biblio(單號)` 補位,EPO OPS 書目涵蓋 TW 公告案(v3 campaign 實證 2 件補齊)。**通則:GPSS 欄位空 ≠ 資料不存在,宣告從缺前沿來源梯補位。**
   - **② EPO OPS**——歐洲專利局官方 API。檢索級由 `patent_search` 內建(search→biblio 二段,受 15/min 節流,大 `num` 會截斷並在 provenance 記 `biblio_truncated`;舊 `epo_search` 工具已下架);單號工具保留:`epo_family`(官方 INPADOC 家族)/ `epo_biblio`(摘要)。**⚠️ 流量限制與計費安全說明**：(1) **免費額度為每週 4 GB**，若超過該流量，API 會直接阻斷連線 (通常返回 HTTP 403 / Quota Exceeded) 而**不會自動扣款**，故無意外產生帳單的風險（若要無限流量需主動付年費 €2,800/年）；(2) 有每 IP 每分鐘約 10 次搜尋的頻率限制，批次呼叫時需做好節流。
   - **③ USPTO PPUBS**(`uspto_patents` + `ppubs_batch_get_claims`)——美國案完整全文 + 附圖文字說明。**取文路徑**:
     - 逐字 Claim 1(US 案最可靠補抓):`ppubs_batch_get_claims(publication_numbers=[...])` 批量回 claim 1,實證對 GPSS 回空的 US 案一次補完整逐字內容。GPSS records 帶 `claim1_empty: true` 即為觸發訊號。
     - 全文:`uspto_patents(method="ppubs_get_full_document", publication_number="US...")` —— 已加 `publication_number` 便利包裝,內部自動完成 pub number → PPUBS 查詢 → guid → 全文,不需手動串兩段 guid。
     - **USPC 軸限縮(GPSS 無此能力)**:GPSS 級只有 `cpc`/`ipc`,**沒有 `uspc`**。要以美國分類(USPC)限縮 US 案,直接 `patent_search(uspc="705/300")` —— dispatcher 會直達 PPUBS,底層以 `CCL/<class>/<subclass>` 語法執行(USPC 軸的唯一可執行路徑;舊 `ppubs_search_*` methods 已下架)。CPC/IPC 可在 GPSS 級一站 AND,USPC 由路由自動跳級。
   - **④ Google Patents BigQuery(`google_*`)——合法註冊 API,不是爬蟲,別跟 `gpatents_*` 混為一談**。走 `GOOGLE_APPLICATION_CREDENTIALS` service account 查 `patents-public-data` 公開資料集(ToS 乾淨、不被限速封鎖)。實測 `google_get_patent_claims` / `google_get_patent_description` 對 US 案乾淨回傳**全部請求項 + 完整說明書全文(含 BRIEF DESCRIPTION OF THE DRAWINGS 逐圖文字說明)**。涵蓋 US/EP/WO/JP/CN/KR/GB/DE/FR/CA/AU(**不含 TW**,TW 走 ①GPSS)。**定位:僅作單號精確手術取文的備援之一,絕不做檢索。**
     - **⚠️ 燒錢工具已下架**:BigQuery 按查詢掃描的欄位量計費,模糊檢索全表掃描極易爆帳單(曾有單次 10 TB ≈ 60 美金、且月用量已實際爆過免費額度)。因此**所有 `google_search_*` 全表掃描工具(`google_search_patents` / `google_search_by_inventor` / `google_search_by_assignee` / `google_search_by_cpc`)已自 MCP 永久移除**——檢索一律走 `patent_search`(官方梯不按掃描量計費,檢索能力一樣有)。
     - **剩餘 BQ 工具(僅 4 個,全部單號或唯讀)**:`google_get_patent`(書目,已收斂為明確欄位、非 `SELECT *`)、`google_get_patent_claims`、`google_get_patent_description`(三者皆 `WHERE publication_number=@x LIMIT 1`,掃描量小)、`google_budget_status`(查本月用量,本身免費不計費)。
     - **雙層成本防護**:(1) **單次封頂**——`config.py` 的 `BIGQUERY_MAX_BYTES_BILLED`(預設 10 GB)限制單次掃描量,超量自動阻斷報錯。(2) **月預算閘門**——`BIGQUERY_MONTHLY_BUDGET_BYTES`(預設 1 TiB = 免費額度)。系統以「本地 SQLite 記帳 + `INFORMATION_SCHEMA.JOBS_BY_PROJECT` 權威校正」混合追蹤本月已計費 bytes;**一旦超額,所有 BigQuery 工具一律硬擋**,回結構化錯誤 `{error_code:"BQ_BUDGET_EXCEEDED", monthly_used_bytes, monthly_budget_bytes, usage_source, suggestion:"改用 GPSS/EPO/PPUBS"}`(fail-fast,不靜默降級)。
     - **用法紀律**:依賴 BQ 取文前,先呼叫 `google_budget_status` 確認 `exceeded=false`;超額時改走 ①GPSS / ②EPO / ③PPUBS 取文。`get_claim1` 與書目補全的 fallback 鏈中,BQ 分支於超額時自動跳過(log 後續往 GPSS)。建議另以 GCP CLI 設專案每日查詢配額(`gcloud alpha services quota update ... --metric=bigquery.googleapis.com/quota/query/usage --value=10240`)當第三層兜底。
     - **限制**:只有文字(claims/description/書目),**沒有圖檔影像或 PDF 連結**;代表圖/PDF 走 `gpatents_*`。
   - **⑤ Google Patents 網頁爬蟲——最後手段**。檢索尾級由 `patent_search(allow_scraping=True)` 閘控(需使用者明確授權;舊 `gpatents_search` 工具已下架);單號取文/圖工具 `gpatents_get`/`gpatents_download_*` 保留,語義不變。這些都爬 patents.google.com 網頁,**非官方、極易被限速封鎖(實測連續 timeout / storage 403 / 頁面 503)**。只在 ①②③④ 都填不了某欄位時才用(它獨有的是 `representative_figure_url` 代表圖縮圖),且須預期失敗、設早退(連 3 次失敗即放棄)。**切勿委派子代理去吸收會 timeout 的 `gpatents_*` 輸出**——子代理會反覆 `worker_dead`。
   - **🖼️ 取 PDF / 代表圖的工具梯(取代舊「PDF 端點系統性故障」論斷)**:
     - **`fetch_patent_pdf(publication_number=..., allow_scraping=False)`——取 PDF 首選**。內部路由 **官方優先**(epo_images OAuth → google_citation 單號解析 → 本地快取)。**預設 `allow_scraping=False`**:官方來源 miss 時**不靜默走 GPSS headless 爬蟲**,改回 `SCRAPING_REQUIRED`,提示需授權。取得使用者同意後傳 `allow_scraping=True` 才會啟用 GPSS 抓取。`provenance.scraping` 欄位標示該次是否走了爬蟲。
     - **`extract_representative_figure(publication_number=..., dpi=200)`——從 PDF 抽代表圖的高階工具**。定位 FIG.1 頁高解析渲染,取代舊「選最大檔」爛策略。回 `NO_FIGURE_PAGE_BUT_IMAGES_PRESENT`(帶 `image_count`)時表示「**圖就在已下載的 PDF 裡**、只是定位器對無文字層掃描版失效」——應從 PDF 抽圖(純 PDF 處理,非爬蟲),不是宣告無圖。
     - **`patentmcp_batch_download_figures(publication_numbers=[...])`——批量抓圖的單線軟性合規機制**(Concurrency=1 + 隨機延遲 + 503 cooldown);TW 案走 GPSS headless,非 TW 走 `extract_representative_figure` PDF 抽圖。
   - **⛔ 爬蟲授權與防護天條 (Scraping & Concurrency Guardrails)**:
     1. **明確口頭同意(門檻不變)**:使用 `gpatents_*` 爬蟲取文、檢索爬蟲尾級(`patent_search(allow_scraping=True)`)、或會觸發 GPSS headless 抓取的路徑(`fetch_patent_pdf(allow_scraping=True)`、`patentmcp_batch_download_figures`、`gpss_download_*`)前,**必須先獲得使用者明確口頭同意**。預設 `allow_scraping=False` 就是為了讓官方路徑優先、不在未授權下偷走爬蟲。
     2. **單線程限速執行**:所有模擬網頁爬蟲永遠只准單線程(Concurrency=1)順序執行,每次請求間強制隨機延遲。
     3. **零臨時腳本繞道**:嚴禁 AI 私下撰寫臨時 Python 爬取/下載腳本繞過工具缺陷;一律提報 `patentmcp` Bug Report 由核心工具層修正。
     4. **🟢 同意後,爬蟲是正規合規路徑(平衡補述)**:`patentmcp_batch_download_figures` 等單線批量軟性機制是 repo **刻意工程收斂出來的合規抓取路徑**——爬蟲不是「能不碰就不碰的紅線」,而是「被收斂成單線+限速+需同意的內建能力」。取得使用者同意後直接認它為正規路徑;`provenance.scraping: true` 是這機制的**正常標記、非違規證據**。AI 讀完此節的正確姿態是:「機制存在、合規、就是設計來幹這個的;我唯一缺的是使用者那句授權」,而非把整個抓圖能力當需要迴避的越界行為。
   - ⚠️ **`google_*`(BigQuery 合法 API)≠ `gpatents_*`(網頁爬蟲)**:工具名都含 "google" 但後端與合法性完全不同。要逐字 claims / 全文 / 圖說,優先用 `google_get_patent*`(④),不要因為名字有 google 就避開。
   - **原始附圖文字說明**可由 ④`google_get_patent_description` 或 ③USPTO PPUBS 可靠取得;**原始圖檔影像**走上方 `fetch_patent_pdf` → `extract_representative_figure` 工具梯(官方 PDF 優先),最後才是 `reference/priorsearch/pdf-figure-extraction.md` 的降級路徑。

## 領域骨幹

人類從業流程與 AI 對應見 `../patent-practitioner-workflow.md`。

## 專利工作池資料樹規範 (Data Tree Specification)

> **單一真相在 `flows/priorsearch.md §0`。** 正式 landscape/前案地圖任務的固化工作資料夾結構(`priorart_<topic>/` 的 `00_campaign.md` / `01_search/`(含 `matrix-log.jsonl` schema) / `02_pool/`(含 candidates.csv 欄位格式) / `03_assets/`(含 5 張統計圖命名) / `04_report/`(docxmcp Mode A package) / `99_deliverables/`)一律以該檔為準,本檔不再平行定義第二套目錄,以免漂移。

要點摘錄(細節見 priorsearch.md §0):

- **工作資料夾根落 `output/`(MUST)**:整包 `priorart_<topic>/` 一律建在專案的 `output/priorart_<topic>/`,**不得**散落專案根目錄(cwd 根)。它整包屬「中間產物 + 衍生交付物」,專案根只留 `input/`(使用者輸入)、最終呈交成品與 `plans/`(治理)。細節與理由見 priorsearch.md §0「落點」。
- **交付物 vs 中間產物物理隔離**:交付物(`<topic>_專利池.xlsx` + `<topic>_技術洞察報告.docx`)落 `99_deliverables/`;檢索中間產物分層落 `01_search/`(原始 JSON + `matrix-log.jsonl`)、`02_pool/`(candidates.csv + shortlist.json)、`03_assets/`(figures + patents)。
- **檢索矩陣紀錄是 `01_search/matrix-log.jsonl`**(每行一筆結構化查詢),既是復現核心,也是 `search_audit` 機檢檢索強度的唯一資料源。
- **candidates.csv 欄位 / 5 張 HSL 統計圖命名**:見 priorsearch.md §0。
- **04_report 對齊 docxmcp**:`manifest.json` + `body.md` + `media/`,可直接 `assemble`。
