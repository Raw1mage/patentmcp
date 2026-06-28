---
name: patentworks
description: 專利全流程工作站。四種任務:(A) 把發明材料/idea 整理成技術交底書;(B) 前案/現況檢索 → 產出已評分、可稽核的人類可讀表格;(C) 針對給定技術想法進行前案檢索、102/103比對與差異分析並產出撰寫基礎;(D) 從技術揭露起草符合各國法規的專利說明書(請求項+說明書+摘要)。當使用者要「整理交底書/挖專利點」「找前案/查有沒有人做過/技術現況」「前案比對與技術特徵分析」或「寫專利說明書/起草專利申請」時使用。檢索重 US/CN;起草分 共通/TW/CN/US/EP 五法域。
---

# PatentWorks

> **搭配 `patentmcp` MCP 使用**:本 skill 是這組工具的劇本;所有檢索/交付工具(`gpss_search`、`epo_family`/`epo_biblio`/`epo_search`、`gpatents_*`、`build_screening_table`、`stage_file`)都來自 patentmcp。沒有該 MCP 時本 skill 無法執行實際檢索。

專利從 idea 到申請的全流程。依需求選一個 flow,**先讀對應 flow 檔再執行**。

## 完整管線

```
disclosure(交底書)→ screening(查新)→ analysis(分析)→ drafting(起草說明書)
發明材料/idea ──────────────────────────────────────────→ 專利申請文件
```
四者可單獨用,也可串成完整旅程;前一段的產出是後一段的輸入。

## 選 flow

| 使用者意圖 | flow |
|---|---|
| 整理交底書 / 從專案材料挖專利點 / 發明揭露 | **`flows/disclosure.md`** |
| 有沒有人做過 / 找前案 / 可專利性 / 技術現況 / landscape(輕量,出 scored CSV) | **`flows/screening.md`** |
| 跨美陸台前案地圖 / 收斂到 N 件 / 要正式 Excel 池 + 技術洞察報告 DOCX | **`flows/priorsearch.md`** |
| 前案檢索與可專利性比對(102/103) / 做要件對照表(Claim Chart) / 製作起草基礎 | **`flows/analysis.md`** |
| 幫我寫專利說明書 / 請求項 / 起草申請 | **`flows/drafting.md`** |

> screening 內部又分「可專利性(要件對照→新穎性綜述)」與「landscape(主題分群→技術地圖)」——細節見該 flow。
> **screening vs priorsearch**:screening 出一張 scored CSV(輕量查新);priorsearch 是 landscape 的重型交付版——建立**固化工作資料夾**(中間產物 + 交付物分層、`04_report/` 結構與 docxmcp package 調和)、跨三地官方 API、收斂件數、產出含逐字 Claim 1 與**檢索方法復現章**的 Excel + DOCX 正式報告。要正式報告走 priorsearch。

## 共用原則(兩 flow 皆適用)

1. **交付物是人類可讀的成品**(screening = scored CSV;drafting = 說明書文件),一律經 patentmcp `stage_file` / docxmcp token+blob handle 交付,bytes 不過 context。
2. **法域意識**:檢索預設 US/CN(TW 低價值);起草須先定目標法域,載入 `reference/drafting/common.md` + 對應法域檔。
3. **法遵以 skill 知識處理,不做工具**:合規/法條要點寫在 `reference/drafting/{common,tw,cn,us,ep}.md`,起草時逐條自檢。
4. **AI 做預篩/起草草稿 + 解釋,人類複核裁決**(專利有法律份量)。
5. **來源優先序——官方 REST API 優先,Google 爬蟲是最後手段**:
   - **⛳ 來源梯窮舉門檻(Exhaustion Gate)——硬規則**:**在報告中宣告任一資料欄位(逐字 Claim 1 / 代表圖 / 全文 / 書目)「從缺 / 無解」之前,必須沿下方來源梯逐級走完,並在報告「誠實缺口」章為每一級留下實測結果(成功 / 失敗 + 失敗原因)。** 只在第①級回空就停手 = **流程缺陷,不是合法降級**。對應 `search_audit`「先驗過程再驗產物」的精神——同一套窮舉思維延伸到「取文/取圖強度」。常見漏走的下一級:
     - **Claim 1 回空** → 走 ③`uspto_patents`(US 案最可靠,實證 `ppubs_batch_get_claims` 一次可補完整逐字 Claim 1);觸發訊號有二:`gpss_search` 回應的 `claim1_audit{empty_count, empty_pubnos[]}`(工具層直接給,列出需補抓的公開號),以及 `gpss_to_records` / `build_screening_table` 的 records 帶 `claim1_empty: true`。
     - **代表圖缺** → 先 `fetch_patent_pdf`(官方路由優先),圖通常**就在已下載的 PDF 裡**;`extract_representative_figure` 對掃描版回 `NO_FIGURE_PAGE_BUT_IMAGES_PRESENT`(帶 `image_count`)時,代表「圖在 PDF 內、只是定位器對無文字層失效」,應從已下載 PDF 抽圖,**不是宣告無圖**。
     - **某工具回空 / 某定位器失敗 ≠ 整件事終局無解**;一律換工具 / 走下一級 / 從已在手的中間產物再加工。
   - **① GPSS**(`gpss_search`,**首選**)——TIPO 官方 REST,一次回 PN/AN/標題/摘要/Claim1/CPC/IPC/申請人/日期,IPC 錨定,一站涵蓋 US/CN/TW。逐字 Claim 1 用 `gpss_search(pub_number=...)` 單號查詢三地通用。**已知限制**:(a) **US 案 Claim 1 偶為空**(只回 "What is claimed is:" 無內文)——records 會帶 `claim1_empty: true`,須走 ③PPUBS 補抓;(b) **不提供 INPADOC 家族 ID**,去重僅到「公開號級」,要家族級 collapse 走 ②`epo_family`;(c) **無 USPC 軸**——`gpss_search` 只有 `cpc`/`ipc`,US 分類限縮須走 ③`uspto_patents`(PPUBS `CCL/<class>/<subclass>` 語法)。
   - **② EPO OPS**(`epo_family` 官方 INPADOC 家族 / `epo_biblio` 摘要 / `epo_search` CQL)——歐洲專利局官方 API。**⚠️ 流量限制與計費安全說明**：(1) **免費額度為每週 4 GB**，若超過該流量，API 會直接阻斷連線 (通常返回 HTTP 403 / Quota Exceeded) 而**不會自動扣款**，故無意外產生帳單的風險（若要無限流量需主動付年費 €2,800/年）；(2) 有每 IP 每分鐘約 10 次搜尋的頻率限制，批次呼叫時需做好節流。
   - **③ USPTO PPUBS**(`uspto_patents` + `ppubs_batch_get_claims`)——美國案完整全文 + 附圖文字說明。**取文路徑**:
     - 逐字 Claim 1(US 案最可靠補抓):`ppubs_batch_get_claims(publication_numbers=[...])` 批量回 claim 1,實證對 GPSS 回空的 US 案一次補完整逐字內容。GPSS records 帶 `claim1_empty: true` 即為觸發訊號。
     - 全文:`uspto_patents(method="ppubs_get_full_document", publication_number="US...")` —— 已加 `publication_number` 便利包裝,內部自動完成 pub number → PPUBS 查詢 → guid → 全文,不需手動串兩段 guid。
     - **USPC 軸限縮(GPSS 無此能力)**:GPSS `gpss_search` 只有 `cpc`/`ipc`,**沒有 `uspc`**。要以美國分類(USPC)限縮 US 案,走 `uspto_patents(method="ppubs_search_patents", query='CCL/705/300')` —— PPUBS 的 `CCL/<class>/<subclass>` 語法是 USPC 軸的唯一可執行路徑。CPC/IPC 可在 GPSS 一站 AND,USPC 須跳到此工具。
   - **④ Google Patents BigQuery(`google_*`)——合法註冊 API,不是爬蟲,別跟 `gpatents_*` 混為一談**。走 `GOOGLE_APPLICATION_CREDENTIALS` service account 查 `patents-public-data` 公開資料集(ToS 乾淨、不被限速封鎖)。實測 `google_get_patent_claims` / `google_get_patent_description` 對 US 案乾淨回傳**全部請求項 + 完整說明書全文(含 BRIEF DESCRIPTION OF THE DRAWINGS 逐圖文字說明)**。涵蓋 US/EP/WO/JP/CN/KR/GB/DE/FR/CA/AU(**不含 TW**,TW 走 ①GPSS)。**定位:僅作單號精確手術取文的備援之一,絕不做檢索。**
     - **⚠️ 燒錢工具已下架**:BigQuery 按查詢掃描的欄位量計費,模糊檢索全表掃描極易爆帳單(曾有單次 10 TB ≈ 60 美金、且月用量已實際爆過免費額度)。因此**所有 `google_search_*` 全表掃描工具(`google_search_patents` / `google_search_by_inventor` / `google_search_by_assignee` / `google_search_by_cpc`)已自 MCP 永久移除**——檢索一律走 ①GPSS / ②EPO / ⑤gpatents,那些不按掃描量計費,檢索能力一樣有。
     - **剩餘 BQ 工具(僅 4 個,全部單號或唯讀)**:`google_get_patent`(書目,已收斂為明確欄位、非 `SELECT *`)、`google_get_patent_claims`、`google_get_patent_description`(三者皆 `WHERE publication_number=@x LIMIT 1`,掃描量小)、`google_budget_status`(查本月用量,本身免費不計費)。
     - **雙層成本防護**:(1) **單次封頂**——`config.py` 的 `BIGQUERY_MAX_BYTES_BILLED`(預設 10 GB)限制單次掃描量,超量自動阻斷報錯。(2) **月預算閘門**——`BIGQUERY_MONTHLY_BUDGET_BYTES`(預設 1 TiB = 免費額度)。系統以「本地 SQLite 記帳 + `INFORMATION_SCHEMA.JOBS_BY_PROJECT` 權威校正」混合追蹤本月已計費 bytes;**一旦超額,所有 BigQuery 工具一律硬擋**,回結構化錯誤 `{error_code:"BQ_BUDGET_EXCEEDED", monthly_used_bytes, monthly_budget_bytes, usage_source, suggestion:"改用 GPSS/EPO/PPUBS"}`(fail-fast,不靜默降級)。
     - **用法紀律**:依賴 BQ 取文前,先呼叫 `google_budget_status` 確認 `exceeded=false`;超額時改走 ①GPSS / ②EPO / ③PPUBS 取文。`get_claim1` 與書目補全的 fallback 鏈中,BQ 分支於超額時自動跳過(log 後續往 GPSS)。建議另以 GCP CLI 設專案每日查詢配額(`gcloud alpha services quota update ... --metric=bigquery.googleapis.com/quota/query/usage --value=10240`)當第三層兜底。
     - **限制**:只有文字(claims/description/書目),**沒有圖檔影像或 PDF 連結**;代表圖/PDF 走 `gpatents_*`。
   - **⑤ Google Patents 網頁爬蟲(`gpatents_*`)——最後手段**。`gpatents_*`(`gpatents_search`/`gpatents_get`/`gpatents_download_*`)爬 patents.google.com 網頁,**非官方、極易被限速封鎖(實測連續 timeout / storage 403 / 頁面 503)**。只在 ①②③④ 都填不了某欄位時才用(它獨有的是 `representative_figure_url` 代表圖縮圖),且須預期失敗、設早退(連 3 次失敗即放棄)。**切勿委派子代理去吸收會 timeout 的 `gpatents_*` 輸出**——子代理會反覆 `worker_dead`。
   - **🖼️ 取 PDF / 代表圖的工具梯(取代舊「PDF 端點系統性故障」論斷)**:
     - **`fetch_patent_pdf(publication_number=..., allow_scraping=False)`——取 PDF 首選**。內部路由 **官方優先**(epo_images OAuth → google_citation 單號解析 → 本地快取)。**預設 `allow_scraping=False`**:官方來源 miss 時**不靜默走 GPSS headless 爬蟲**,改回 `SCRAPING_REQUIRED`,提示需授權。取得使用者同意後傳 `allow_scraping=True` 才會啟用 GPSS 抓取。`provenance.scraping` 欄位標示該次是否走了爬蟲。
     - **`extract_representative_figure(publication_number=..., dpi=200)`——從 PDF 抽代表圖的高階工具**。定位 FIG.1 頁高解析渲染,取代舊「選最大檔」爛策略。回 `NO_FIGURE_PAGE_BUT_IMAGES_PRESENT`(帶 `image_count`)時表示「**圖就在已下載的 PDF 裡**、只是定位器對無文字層掃描版失效」——應從 PDF 抽圖(純 PDF 處理,非爬蟲),不是宣告無圖。
     - **`patentmcp_batch_download_figures(publication_numbers=[...])`——批量抓圖的單線軟性合規機制**(Concurrency=1 + 隨機延遲 + 503 cooldown);TW 案走 GPSS headless,非 TW 走 `extract_representative_figure` PDF 抽圖。
   - **⛔ 爬蟲授權與防護天條 (Scraping & Concurrency Guardrails)**:
     1. **明確口頭同意(門檻不變)**:使用 `gpatents_*` 爬蟲、或會觸發 GPSS headless 抓取的路徑(`fetch_patent_pdf(allow_scraping=True)`、`patentmcp_batch_download_figures`、`gpss_download_*`)前,**必須先獲得使用者明確口頭同意**。預設 `allow_scraping=False` 就是為了讓官方路徑優先、不在未授權下偷走爬蟲。
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
- **交付物 vs 中間產物物理隔離**:交付物(`<topic>_專利池.xlsx` + `<topic>_技術洞察報告.docx`)落 `99_deliverables/`;檢索中間產物分層落 `01_search/`(原始 JSON + `matrix-log.jsonl`)、`02_pool/`(candidates.csv + shortlist.json)、`03_assets/`(figures + patents)。
- **檢索矩陣紀錄是 `01_search/matrix-log.jsonl`**(每行一筆結構化查詢),既是復現核心,也是 `search_audit` 機檢檢索強度的唯一資料源。
- **candidates.csv 欄位 / 5 張 HSL 統計圖命名**:見 priorsearch.md §0。
- **04_report 對齊 docxmcp**:`manifest.json` + `body.md` + `media/`,可直接 `assemble`。

