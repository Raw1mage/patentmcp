# Flow: Prior-Art Landscape Search(三地前案地圖檢索)

把一個技術主題,變成 **(1) 一份可稽核的專利池 Excel** + **(2) 一份含逐字 Claim 1 與檢索方法章的技術洞察報告 DOCX**,全程落在一個**固化工作資料夾**內(中間產物 + 交付物分層留存,可復現、可交接)。

> 這是 `screening.md`「landscape」子情境的**重型交付版**。輕量查新(出一張 scored CSV)仍走 `screening.md`;要正式 Excel 池 + 技術洞察報告 DOCX 走本 flow。

## 0. 固化工作資料夾(與 docxmcp src package 調和)

每個檢索任務建立一個工作資料夾,結構固定。`04_report/` 直接採 docxmcp 文字文件 package 慣例(`manifest.json` + `body.md` + `media/`),使其能無痛餵進 docxmcp Mode A assemble。

> **落點(MUST)**:工作資料夾根 `priorart_<topic>/` **一律建在專案的 `output/` 底下**(即 `output/priorart_<topic>/`),**不得**散落在專案根目錄(cwd 根)。理由:`priorart_<topic>/` 整包是任務的「中間產物 + 衍生交付物」(原始檢索 JSON、候選池、素材圖、報告 package、最終 DOCX/XLSX),全部屬於產出物範疇;專案根目錄只保留使用者輸入面(`input/`)、最終呈交給使用者的成品,以及計畫治理檔(`plans/`)。把工作資料夾落在根層會污染交付目錄根、混淆「輸入 vs 產出」邊界。若專案無 `output/` 則先建立。

```
output/priorart_<topic>/             ← 工作資料夾根(一案一夾,落在 output/ 下)
├── 00_campaign.md                   ← 檢索計畫:主題/IPC錨點/三地/日期/件數目標/硬條件
├── 01_search/                       ← 檢索中間產物(完整 search history;API quota 換來的資料一律落地,見保存契約)
│   ├── probes.md                    ← 校準探針結果(各錨點小量試打的命中量級)
│   ├── matrix-log.jsonl             ← 完整檢索矩陣紀錄(每行一筆查詢,結構化 schema)← 可復現核心 + search_audit 機檢來源
│   └── raw/                         ← 每一次 API 呼叫的原始回應(大檔,不進主 context;命名固定)
│       ├── Q<NN>.json               ← 每條 matrix 查詢的完整原始回應(對應 matrix-log 的 raw_ref)
│       ├── probe_<地區>_<群>.json    ← 校準探針原始回應(TW/CN/US × 概念群 A-E)
│       └── full_<pubno>.json        ← shortlist 深挖取的逐字 claims/全文/家族原始回應
├── 02_pool/                         ← 專利池
│   ├── candidates.csv               ← 去重+硬條件篩選後的候選池(書目+技術摘要+情境分類+1-5級相關性)
│   └── shortlist.json               ← 針對所有評等為 5 級相關性專利的深挖數據(包含逐字 Claim 1、代表圖路徑與完整圖說文字)
├── 03_assets/                       ← 報告素材
│   ├── figures/                     ← 統計圖表 PNG(matplotlib 產)
│   └── patents/                     ← 針對已知專利小量下載的原始 PDF(見 §5)
├── 04_report/                       ← docxmcp Mode A package(格式同 docxmcp 文字文件 src)
│   ├── manifest.json                ← {"format":"docx","title":...,"body":"body.md","media_dir":"media"}
│   ├── body.md                      ← 報告全文(完整 #/##/### 階層,含 §1 檢索方法復現章)
│   └── media/                       ← 報告引用的圖檔(從 03_assets/figures 複製,引用寫 media/xxx.png)
└── 99_deliverables/                 ← 最終交付物
    ├── <topic>_專利池.xlsx
    └── <topic>_技術洞察報告.docx
```

**為何 04_report 要對齊 docxmcp**:docxmcp `decompose` 產出的文字文件 package 就是 `manifest.json` + `body.md`(或 `chapters/*.md`)+ `media/` + `outline.md` + `content_list.json`。報告 package 採同結構 → tar 上傳即可直接 `assemble`,且日後若要反向 `decompose` 修訂也同構。詳見 `../reference/priorsearch/docx-assembly.md`。

### `matrix-log.jsonl` schema(可復現核心 + 機檢來源)

每跑一條查詢就 **append 一行 JSON** 到 `01_search/matrix-log.jsonl`。這是 `search_audit` 機檢檢索強度的唯一資料源,也是報告 §1 復現表的來源。零命中也要記(零命中是有效證據)。

```json
{
  "query_id": "Q07",
  "source": "gpss",
  "database": "USA",
  "axis": {
    "class_codes": ["G06Q20/02"],
    "class_scheme": "cpc",
    "keywords": ["milestone payment"],
    "concept_group": "C",
    "boolean": "AND",
    "date_from": "2015-01-01",
    "date_to": "2026-06-28"
  },
  "hits": 42,
  "raw_ref": "raw/Q07.json"
}
```

| 欄位 | 意義 | 不允許 |
|---|---|---|
| `query_id` | 查詢序號(復現錨) | 跳號或重複 |
| `source` | `gpss`/`epo`/`uspto`/`google` | 爬蟲 `gpatents_*` |
| `database` | `TWA/TWB/CNA/CNB/USA/USB` 或 epo/google region | 留空 |
| `axis.class_codes` | 該查詢實際用的分類碼(可多) | 填願望而非實際送出值 |
| `axis.class_scheme` | `ipc`/`cpc` | 與 class_codes 不符 |
| `axis.concept_group` | 對應 campaign 概念群 A-E | 未在 campaign 定義 |
| `axis.boolean` | `AND`/`OR`/`SINGLE` | 全程 SINGLE 單詞海撈 |
| `hits` | 命中數(0 也記) | 漏記 |
| `raw_ref` | 該查詢原始回應落地路徑(`raw/Q<NN>.json`) | 留空 / 指向不存在的檔 |

### Search-history 保存契約(硬規定:每滴 API quota 都要落地)

**動機**:檢索的原始回應是用 **API quota 換來的有限資源**——GPSS REST、BigQuery(按掃描量計費)、EPO(每週 4GB 上限)每一次呼叫都有實質成本。若只把蒸餾後的 `candidates.csv` 留下、丟棄原始回應,則任何複查、改良、重新評分、補欄位都得**重新花 quota 再打一次**,這是浪費。`01_search/` 必須是一份**完整、自足、可離線復現**的 search history。

**硬規則(交付前必檢,違反即不合格):**

1. **每一次 API 呼叫的原始回應一律落地 `01_search/raw/`,不得只進主 context 後丟棄。** 包含:matrix 正式查詢(`Q<NN>.json`)、校準探針(`probe_<地區>_<群>.json`)、shortlist 深挖的逐字 claims/全文/家族(`full_<pubno>.json`)。命名固定見 §0 樹。
2. **matrix-log 每一行的 `raw_ref` 必須指向實際存在的檔。** `search_audit` PASS 不代表 history 完整;`raw_ref` 懸空(指向不存在的檔)是 history 殘缺,等同浪費了那次 quota。
3. **零命中也要落地。** 零命中的原始回應(空 result set)是有效的負面證據,證明該分類×關鍵字組合確實查過,避免日後重打。
4. **probes.md 記命中量級,raw/ 記探針原始回應。** 兩者並存——`probes.md` 是人讀的校準摘要,`probe_*.json` 是機器可復現的原始證據。
5. **下載的原始 PDF / 代表圖落地 `03_assets/patents/`(見 §5),不留在 token store。** token store 會過期清除;用 quota(或同意後的軟性抓取)換來的 PDF/圖一律複製進工作資料夾。
6. **完工自檢:`raw/` 的檔數應 ≥ matrix-log 行數 + probe 數 + shortlist 深挖數。** 缺檔代表有 quota 換來的資料沒落地——回補,不得交付殘缺 history。

> 一句話:**凡是花 quota 打出去的,回應就要進 `01_search/`。** 蒸餾池(`candidates.csv`)是衍生視圖,原始回應(`raw/`)才是不可再生的一手證據。

### `01_search/index.jsonl` — 檢索行為索引檔(必備)

`matrix-log.jsonl` 記的是**檢索式的結構化軸**(供 `search_audit` 機檢);`index.jsonl` 記的是**每次撈取行為的人讀帳本**——用了什麼檢索式、從哪個來源/資料庫撈、撈回幾筆、原始回應實體落在哪。兩者並存:matrix-log 是機檢真相,index 是復現與稽核帳本。

**每一次撈取(matrix 查詢 / 探針 / 單件深挖 / PDF·圖下載)都 append 一行:**

```json
{
  "ts": "2026-06-28T18:07:00+08:00",
  "kind": "matrix_query",
  "query_id": "Q07",
  "tool": "gpss_search",
  "request": {"database": "USA", "class_scheme": "cpc", "class_codes": ["G06Q20/02"], "keywords": ["milestone payment"], "boolean": "AND", "date_from": "2015-01-01", "date_to": "2026-06-28"},
  "hits": 42,
  "artifact": "raw/Q07.json",
  "bytes": 51234
}
```

| `kind` | 用途 | `artifact` 指向 |
|---|---|---|
| `matrix_query` | 正式矩陣查詢 | `raw/Q<NN>.json` |
| `probe` | 校準探針 | `raw/probe_<地區>_<群>.json` |
| `deep_dive` | shortlist 逐字 claims/全文/家族 | `raw/full_<pubno>.json` |
| `entity_download` | 單件實體(PDF/XML/圖) | `03_assets/patents/<PN>/...` 或 patentdb 路徑(見 §5) |

**硬規則:**
1. **每一筆撈取行為都有 index 一行,`artifact` 必指向實際存在的檔。** index 行數應 = `raw/` 檔數 + 實體下載數;對不上代表有資料沒記帳或沒落地。
2. **單件實體下載(PDF/XML/圖)必記 `entity_download` 行**,並在 `request` 記公開號、來源工具、是否經同意爬取(`scraping: true/false`),`artifact` 指向落地路徑。
3. **index 是離線可復現的帳本**——任何後續 AI 讀 `index.jsonl` 就能知道「這個池子的每一筆是怎麼來的、原始檔在哪」,不必重打 API。

### `02_pool/candidates.csv` 欄位格式(統一真相)

去重 + 硬條件篩選後的候選池(≥20 篇),欄位順序固定:

```
#,類別,代表專利號,申請人,優先權,國別,標題,推測CPC,相關性(1-5級),技術要點(蒸餾),命中要件,家族成員,連結,人工複核
```

`相關性(1-5級)`:1=無關 / 2=低度 / 3=中度 / 4=高度 / 5=極相關(最接近前案)。Excel 交付物須附完整 Title/Abstract/Claim 內文作可稽核基礎。

### `03_assets/figures/` 5 張統計圖命名(matplotlib,HSL 配色,報告穩定引用)

| 檔名 | 用途 |
|---|---|
| `fig1_country.png` | 專利國別分佈直方圖 |
| `fig2_relevance.png` | 專利**相關性**(1-5級)分佈直方圖(舊名 `fig2_scenario.png` 為 legacy alias) |
| `fig3_ipc.png` | 主要 IPC/CPC 分類分佈橫向條形圖 |
| `fig4_category.png` | 專利清單類別佔比圓餅圖 |
| `fig5_year.png` | 專利優先權年份分佈折線/條形圖 |

> 宏觀分析從 Excel 數據做數字統計與趨勢觀察即可,**不需逐件線上讀取**(避免超時);5 張圖一律 matplotlib 產、HSL 配色、寫入報告 §2。

## 1. 來源與紅線(硬規定)

- **官方 REST API 優先**。檢索主力 **TIPO GPSS**(`gpss_search`,一站涵蓋 US/CN/TW);全文/圖說文字補 **`google_*` BigQuery 合法 API**(非 TW)、**EPO OPS**、**USPTO PPUBS**。各來源能力與優先序見 `../SKILL.md` §5。
- **🚫 網頁爬蟲非法,禁用**。`gpatents_*`(`gpatents_search`/`gpatents_get`/`gpatents_download_*`)爬 patents.google.com 網頁,**一律不得用於本 flow 的檢索與批量抓取**。
- **`google_*`(BigQuery 合法 API)≠ `gpatents_*`(爬蟲)**:前者走註冊 service account 查公開資料集,合法可靠;要逐字 claims/全文/圖說用 `google_get_patent_claims` / `google_get_patent_description`。
- **原始專利 PDF 下載**:見 §5——**僅允許針對已知專利號、逐件小量下載公開 PDF**,不得批量。
- **CPC/IPC 一次性錨定鐵則**：CPC/IPC 分類代碼**必須作為基本限制條件（即 AND 運算子）直接寫入原始檢索條件式中**。嚴禁在檢索結果返回後進行「第二輪二次 CPC 篩選」，以防因定義偏差誤殺原先有相關的專利。原始檢索後應直接產出包含所有相關專利的大池，僅進行同案去重與相關性評等。

## 1.5 檢索強度契約(硬地板,機檢)

> **這是治本條款。** 過去「隨便檢幾條就交差」之所以能過關,是因為所有檢查只驗產物品質、不驗檢索廣度。本契約把「檢索夠不夠廣」變成 `search_audit` 工具可機檢的 PASS/FAIL 閘——**未 PASS 不得進入交付**。

每次 priorsearch 的 `matrix-log.jsonl` 必須滿足以下**硬地板**(campaign 可往上調,不可往下破):

| 維度 | 硬地板 | 意義 |
|---|---|---|
| 分類錨點數 | **≥ 3** | 跨 IPC/CPC 至少 3 個不同分類碼(不可只圍一個 G06Q 近似碼海撈) |
| 關鍵字概念群 | **≥ 3** | campaign 定義的 A-E 概念群至少觸及 3 群(不可單概念反覆換詞) |
| 三地覆蓋 | **= 3** | TW+CN+US 皆須有查詢(刻意排除須在 campaign 記 `exclude_jurisdiction=<地> reason=...`) |
| AND/OR 組合型態 | **≥ 2** | 至少 2 種布林型態,不可全 `SINGLE` 單詞海撈(分類×關鍵字、關鍵字 OR 同義詞…) |
| 總查詢筆數 | **≥ 12** | 多維交叉的最低笛卡兒覆蓋 |

> **分類軸只用 CPC/IPC(使用者規則 2026-06-28)。** USPC 不納入檢索軸——GPSS `gpss_search` 本就只有 `cpc`/`ipc` 參數;主檢索一律 CPC/IPC 錨定,不要求 USPC。

**campaign 覆寫語法**(寫在 `00_campaign.md`,HTML 註解標記,raise-only):
```
<!-- audit: min_queries=20 min_concept_groups=4 exclude_jurisdiction=TW reason="TW 該領域低價值" -->
```
往下調門檻會被忽略(地板贏);排除某地必帶 reason,否則 audit 仍判缺地。

## 2. GPSS 三地檢索鐵則 + 分類軸

| 國別 | 資料庫代碼 | 關鍵字語言 | 分類軸(CPC/IPC only) |
|---|---|---|---|
| 臺灣 | `TWA`(公開) `TWB`(公告) | **中文** | `ipc` |
| 大陸 | `CNA`(公開) `CNB`(公告) | **中文** | `ipc` |
| 美國 | `USA`(公開) `USB`(公告) | **英文** | `ipc` / `cpc` |

- **分類軸只用 CPC/IPC(使用者規則 2026-06-28)。** 不使用 USPC——`gpss_search` 本就只有 `cpc`/`ipc` 參數。
- **關鍵字語言必須匹配資料庫**(US 庫搜中文回零筆)。
- **TW/CN 共通分類用 `ipc` 參數**(GPSS 的 `cpc` 對 TW 常回零);US 案 `ipc`/`cpc` 皆可。
- **多分類錨點仍是硬要求**:跨 IPC/CPC 至少 3 個不同分類碼(不可只圍一個 G06Q 近似碼海撈)。
- **keyword 用單一複合詞**(多詞空格 AND 常回 `No record`);多概念交叉靠 `分類軸(ipc/cpc) × 單關鍵字 × 日期`,並刻意變換布林型態(AND 限縮 / OR 擴同義詞),不可全程單詞海撈。
- 逐字 Claim 1 三地通用:`gpss_search(pub_number="...")`。

## 3. 流程

### A. 建夾 + 校準
1. 建工作資料夾(§0 結構),寫 `00_campaign.md`(主題/IPC 錨點/三地/日期區間/件數上限/硬條件/加分維度)。
2. 用 `gpss_search` 對每個 IPC 錨點 + 代表關鍵字跑**小量探針**(`num=2~5`),把命中量級記入 `01_search/probes.md`。過寬(數千筆)收緊 IPC/加日期;過窄換上層分類/補同義詞。

### B. 召回 + 落地(委派子代理)
3. 委派**一個**子代理跑完整檢索矩陣(`各分類錨點(ipc/cpc) × 各情境關鍵字概念群 × 三地資料庫 × 日期 × 布林型態`),須滿足 §1.5 檢索強度契約的硬地板:
   - **明令只用官方 API**(`gpss_search` 為主,必要時 `epo_*` / `uspto_patents` / `google_*` BigQuery),**嚴禁 `gpatents_*` 爬蟲**。
   - **每跑一條查詢就 append 一行**到 `01_search/matrix-log.jsonl`(schema 見 §0),`axis` 如實記錄該條實際送出的分類軸/關鍵字/概念群/布林/日期與命中數——這是 `search_audit` 機檢的唯一證據,**不是事後補的願望清單**。
   - 子代理:吸收巨量 JSON(落地 `01_search/raw/`)→ 硬條件過濾 → 同案去重(公開 A/公告 B)→ 收斂至件數上限 → 寫 `02_pool/candidates.csv`。**此過程嚴禁施加任何第二輪 CPC 條件篩選，維持檢索式所定範疇**。
4. 主代理**兩段複核**(先過程、再產物——順序不可顛倒):
   1. **檢索強度閘(先)**:對 `01_search/matrix-log.jsonl` 跑 `search_audit(matrix_log_path=..., campaign_path="00_campaign.md")`。**verdict 必須 PASS** 才能前進;若 `FAIL`,讀 `gaps` 逐條補檢索(回 step 3 補錨點/概念群/三地/布林/筆數),**不得跳過、不得帶 FAIL 進交付**。`WARN`(分佈偏斜)應評估是否補強。
   2. **池子品質複核(後)**:正規 CSV parser(非 awk)確認 `candidates.csv` 件數、無欄位錯位、無重複公開號、相關性（1-5級）標記齊全、三地與情境分佈合理。
4.5 **腳踏兩條船——並查 patentdb 全域庫(DD-12)**:除了本案線上檢索,**並行 `patentdb_query`**(FTS 主題詞 / country / 分類)查跨案累積的全域書目庫,看有沒有本案沒撈到、但適合的分析標的。命中的庫存前案**併入 `candidates.csv`**(來源標 `from_patentdb`),一起評分、一起進報告。庫越大,新案越省 quota、覆蓋越廣——這是 patentdb 對專案的正回饋。注意:patentdb 是被動累加的常用資產,不保證涵蓋偏門領域,查無命中屬正常,不取代線上檢索矩陣。

### C. 重點前案深挖(針對所有評等為 5 級相關性的專利進行，不再受限於固定數量限制) → `02_pool/shortlist.json`
5. 針對所有評等為 5 級的重點專利，逐件取**逐字 Claim 1 + 完整全文/圖說**,依法域選來源：
   - **TW 案**:`gpss_search(pub_number="TW...", databases=["TWA","TWB"])`。
   - **US/EP/WO/JP/CN/KR/… 案(非 TW)**:`google_get_patent_claims(...)` + `google_get_patent_description(...)`(BigQuery 合法 API,回全部請求項 + 完整說明書含 BRIEF DESCRIPTION OF THE DRAWINGS 逐圖文字說明)。
   - **US 案次選**:`uspto_patents(method="ppubs_get_full_document", guid=...)`。
6. **代表圖(圖檔影像)**：優先呼叫 `gpss_download_representative_figure` (TW 案優先，見 §5 與 `../reference/priorsearch/pdf-figure-extraction.md`) 取得絕對圖檔網址並完成下載。

### D. 交付物產出 → `99_deliverables/`
> **交付前最終強制閘**：再跑一次 `search_audit(matrix_log_path="01_search/matrix-log.jsonl", campaign_path="00_campaign.md")`,**verdict 必須 PASS**。這道閘與下方 docx probe `ok=True` 並列——任一不過,不得宣稱交付完成。檢索強度未達標的報告是不合格品,不是「先交再補」。
7. **Excel 專利池**(`xlsx` skill / openpyxl):書目主表(格式化/autofilter/凍結首列/三地色票)+ 統計分頁(國別/情境/IPC/年份)。產出後 **LibreOffice recalc** 驗證零錯誤。
8. **技術洞察報告 DOCX**(docxmcp **Mode A**,組 package 於 `04_report/`):流程見 `../reference/priorsearch/docx-assembly.md`,**probe 驗證 `ok=True` 才算交付**。報告章節見 §4。

## 4. 報告章節(§1 為使用者強制要求)

- **§1 檢索方法與可復現步驟**(必含,讓後續 AI 能復現並改良):引擎與來源優先序、三地資料庫代碼、IPC/CPC 分類錨點、三地關鍵字矩陣。**必須以 Markdown 結構化表格詳細記錄每一則檢索的查詢條件式、分類軸(ipc/cpc)、布林型態、使用的資料庫來源、以及回傳的結果數量**——此表由 `01_search/matrix-log.jsonl` 渲染而來(JSONL 是真相源,表是衍生視圖)。**須附 `search_audit` 的 PASS 結論與覆蓋率數字作為檢索強度佐證**。內容取自 `00_campaign.md` + `01_search/matrix-log.jsonl`。
- §2 專利池全局分佈(嵌統計圖表)
- §3 各情境技術洞察(白話套路 + 差異化主軸)
- **§4 重點前案細部分析**(針對所有評等為 5 級的專利)：包含書目資料、逐字 Claim 1、代表圖與附圖文字說明，以及「**白話技術解析**」區塊。該解析必須在充分理解 Claim 請求項內容後，以白話文重新闡述並回答四個核心問題：
  1. 主要解決什麼問題。
  2. 採用了什麼技術手段/方法。
  3. 獲得專利的獨到關鍵點是哪個步驟或核心技術（新穎性特徵）。
  4. 對於實作「目標產品/開發主題（例如：長照智慧家庭）」的產品開發有什麼啟發與具體建議。
- §5 策略建議
- §6 檢索限制與誠實缺口

## 5. 原始專利 PDF / 代表圖(全域 patentdb 為實體庫,每案一致採用)

### 5.1 patentdb — 跨專案專利資產庫(雙層,架構工具,每次檢索都一致採用)

patentdb 是 patentmcp repo 內的**跨專案全域專利庫**,目的是**積累已檢索的書目與實體、跨案複用、減少重複上網的 API/頻寬成本**——同一件專利在 A 案查過/下載過,B 案直接命中本地,不再花 quota。它是**雙層**架構(規範見 `patentdb/README.md`):

| 層 | 實體 | 角色 |
|---|---|---|
| **結構化層** | `patentdb.sqlite` | 全域書目統一資料庫——一件專利一列、FTS5 全文檢索、跨案複用、承載百萬級書目 |
| **實體 blob 層** | `<國別>/<正規化號>/` | PDF/XML/figures + `metadata.json`,下載工具 write-through 落地 |

```
patentdb/                            ← 全域庫(patentmcp repo 根,非工作資料夾)
├── patentdb.sqlite                  ← 結構化層:patents 書目表 + patents_fts 全文(trigram, CJK)
└── <國別>/                          ← 實體 blob 層 TW/US/CN/EP/WO...
    └── <正規化專利號>/                ← I854998 / 20230081319 / 120543023...
        ├── metadata.json            ← 完整書目詮釋(pubno/title 多語/申請號/日期/發明人/申請人/摘要/CPC/IPC)
        ├── specification.pdf        ← 原檔 PDF
        ├── specification.xml        ← 結構化全文 XML(GPSS dc.xml;TW 案最佳)
        └── figures/                 ← 由 PDF/XML 抽出的圖式
```

**自動化現況(已實作,非手動)**:書目與實體的入庫**由工具自動完成,不需 AI 手動填**——
- `build_screening_table` 拿到 CSV 的當下**inline 自動吸收書目**進 `patentdb.sqlite`(DD-11,零額外 toolcall)。
- `fetch_patent_pdf` / `gpss_download_patent_pdf/xml` 下載成功即 **write-through** 落 blob + register 書目(side-effect,失敗不阻斷)。
- 三個工具供主動操作:`patentdb_query`(pubno 精查 / FTS / country 過濾,回 completeness)、`patentdb_put`(漸進 upsert)、`patentdb_import_csv`(回填歷史 CSV)。

**取用協定(每件一致流程):**

1. **先查本地**:要某件書目/實體前,先 `patentdb_query(publication_number="<PN>")` 或看 `patentdb/<國別>/<正規化號>/`。命中就直接用,**不重打 API**(這正是 patentdb 存在的理由)。
2. **未命中才下載**:逐件 `fetch_patent_pdf(publication_number="<PN>")`(內部試 `epo_images` 官方 → `google_citation` 雜湊 URL);TW 結構化全文走 GPSS `dc.xml`。**逐件、目標明確、合法。**⚠️ 不要自己拼 `/pdfs/<PN>.pdf`(GCS 回 403)。
3. **自動落地**:下載成功工具自動寫 blob + register 書目進 sqlite(含 sha256 + acquisition_cost)。抽圖用 docxmcp `decompose(format=pdf)`,圖落該件 `figures/`。
4. **工作資料夾引用,不重複存**:`priorart_<topic>/03_assets/patents/` 對 patentdb 實體建引用/複本,報告引用其路徑。單一真相在 patentdb。
5. **記帳**:每次實體下載在 `01_search/index.jsonl` append `entity_download`(見 §0),`artifact` 指向 patentdb 路徑,記 `scraping: true/false`。

> 一句話:**書目與實體的家是全域 `patentdb/`。** 先查 patentdb、未命中才下載、取得即自動入庫——每滴 quota 換來的資料跨案複用,不重複花。

### 5.2 能力現況與降級

- **能力現況**(實證):見 `../reference/priorsearch/pdf-figure-extraction.md`。文字(claims/description/圖說)走 GPSS/USPTO PPUBS(+ BigQuery,注意預算);**原始 PDF/圖檔**走 `fetch_patent_pdf`(已實作、端到端驗證,含 TW 案)。代表圖另有 `extract_representative_figure`(掃描版回 `NO_FIGURE_PAGE_BUT_IMAGES_PRESENT` + image_count,提示人工挑選)、`gpss_download_representative_figure`(GPSS headless,需同意爬取)、`batch_download_figures`(單線批量軟性抓圖,需同意)。
- **取不到圖檔影像時**:以「逐字 Claim 1 + 附圖文字說明」(§3-C)替代,並在報告 §4/§6 誠實標註缺口(不可靜默略過)。

## Token 紀律
探針只取必要欄;巨量召回由子代理落地 `01_search/raw/`、不回主 context;完整 claims/全文只對 shortlist 取;每讀一篇蒸餾成 ~50 token 寫回 `candidates.csv`。

## ⚠️ 糾正與優化條款 (USER Corrections)
1. **宏觀分析與 HSL 圖表繪製**：做整批專利的宏觀分析時，不需要逐件線上讀取（避免超時）。大部份是從 Excel 表上的數據進行數字統計與趨勢觀察，必須使用 matplotlib 繪製 5 張符合 HSL 配色之精美統計圖表（地域、評分、分類、佔比、趨勢）並寫入報告中。
2. **專利池 1~5 相關性評分**：專利池 CSV 與 Excel 對照表中必須提供 `Relatedness Score` 欄位（1 至 5 級評分），且 Excel 必須提供完整的 Title/Abstract/Claim 內文作為可稽核基礎。
3. **5分專利逐件細部分析**：只有評分為 **5分 (高度相關)** 的重點專利，才需要在最後一個章節進行「逐件深度洞察評析」，且必須附上代表圖。若 TIPO 等官方圖片伺服器連線超時，應在報告中誠實標註該缺口，降級為 Claim 1 與文字描述。
