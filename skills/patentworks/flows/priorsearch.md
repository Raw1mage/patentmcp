# Flow: Prior-Art Landscape Search(三地前案地圖檢索)

把一個技術主題,變成 **(1) 一份可稽核的專利池 Excel** + **(2) 一份含逐字 Claim 1 與檢索方法章的技術洞察報告 DOCX**,全程落在一個**固化工作資料夾**內(中間產物 + 交付物分層留存,可復現、可交接)。

> 這是 `screening.md`「landscape」子情境的**重型交付版**。輕量查新(出一張 scored CSV)仍走 `screening.md`;要正式 Excel 池 + 技術洞察報告 DOCX 走本 flow。

## 0. 固化工作資料夾(與 docxmcp src package 調和)

每個檢索任務建立一個工作資料夾,結構固定。`04_report/` 直接採 docxmcp 文字文件 package 慣例(`manifest.json` + `body.md` + `media/`),使其能無痛餵進 docxmcp Mode A assemble。

```
priorart_<topic>/                    ← 工作資料夾根(一案一夾)
├── 00_campaign.md                   ← 檢索計畫:主題/IPC錨點/三地/日期/件數目標/硬條件
├── 01_search/                       ← 檢索中間產物
│   ├── probes.md                    ← 校準探針結果(各錨點小量試打的命中量級)
│   ├── matrix-log.md                ← 完整檢索矩陣紀錄(每條查詢:來源/參數/命中數)← 可復現核心
│   └── raw/                         ← 子代理落地的原始 JSON(大檔,不進主 context)
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

## 1. 來源與紅線(硬規定)

- **官方 REST API 優先**。檢索主力 **TIPO GPSS**(`gpss_search`,一站涵蓋 US/CN/TW);全文/圖說文字補 **`google_*` BigQuery 合法 API**(非 TW)、**EPO OPS**、**USPTO PPUBS**。各來源能力與優先序見 `../SKILL.md` §5。
- **🚫 網頁爬蟲非法,禁用**。`gpatents_*`(`gpatents_search`/`gpatents_get`/`gpatents_download_*`)爬 patents.google.com 網頁,**一律不得用於本 flow 的檢索與批量抓取**。
- **`google_*`(BigQuery 合法 API)≠ `gpatents_*`(爬蟲)**:前者走註冊 service account 查公開資料集,合法可靠;要逐字 claims/全文/圖說用 `google_get_patent_claims` / `google_get_patent_description`。
- **原始專利 PDF 下載**:見 §5——**僅允許針對已知專利號、逐件小量下載公開 PDF**,不得批量。
- **CPC/IPC 一次性錨定鐵則**：CPC/IPC 分類代碼**必須作為基本限制條件（即 AND 運算子）直接寫入原始檢索條件式中**。嚴禁在檢索結果返回後進行「第二輪二次 CPC 篩選」，以防因定義偏差誤殺原先有相關的專利。原始檢索後應直接產出包含所有相關專利的大池，僅進行同案去重與相關性評等。

## 2. GPSS 三地檢索鐵則

| 國別 | 資料庫代碼 | 關鍵字語言 | 分類碼參數 |
|---|---|---|---|
| 臺灣 | `TWA`(公開) `TWB`(公告) | **中文** | `ipc` |
| 大陸 | `CNA`(公開) `CNB`(公告) | **中文** | `ipc` |
| 美國 | `USA`(公開) `USB`(公告) | **英文** | `ipc` |

- **關鍵字語言必須匹配資料庫**(US 庫搜中文回零筆)。
- **三地共通分類用 `ipc` 參數**(GPSS 的 `cpc` 對 TW 常回零)。
- **keyword 用單一複合詞**(多詞空格 AND 常回 `No record`);多概念交叉靠 `ipc` + 單關鍵字 + 日期三軸。
- 逐字 Claim 1 三地通用:`gpss_search(pub_number="...")`。

## 3. 流程

### A. 建夾 + 校準
1. 建工作資料夾(§0 結構),寫 `00_campaign.md`(主題/IPC 錨點/三地/日期區間/件數上限/硬條件/加分維度)。
2. 用 `gpss_search` 對每個 IPC 錨點 + 代表關鍵字跑**小量探針**(`num=2~5`),把命中量級記入 `01_search/probes.md`。過寬(數千筆)收緊 IPC/加日期;過窄換上層分類/補同義詞。

### B. 召回 + 落地(委派子代理)
3. 委派**一個**子代理跑完整檢索矩陣(`各 IPC 錨點 × 各情境關鍵字 × 三地資料庫 × 日期`):
   - **明令只用官方 API**(`gpss_search` 為主,必要時 `epo_*` / `uspto_patents` / `google_*` BigQuery),**嚴禁 `gpatents_*` 爬蟲**。
   - 子代理:吸收巨量 JSON(落地 `01_search/raw/`)→ 硬條件過濾 → 同案去重(公開 A/公告 B)→ 收斂至件數上限 → 寫 `02_pool/candidates.csv`。**此過程嚴禁施加任何第二輪 CPC 條件篩選，維持檢索式所定範疇**。
   - 每條查詢的來源/參數/命中數寫入 `01_search/matrix-log.md`(復現用)。
4. 主代理**複核** `candidates.csv`:正規 CSV parser(非 awk)確認件數、無欄位錯位、無重複公開號、相關性（1-5級）標記齊全、三地與情境分佈合理。

### C. 重點前案深挖(針對所有評等為 5 級相關性的專利進行，不再受限於固定數量限制) → `02_pool/shortlist.json`
5. 針對所有評等為 5 級的重點專利，逐件取**逐字 Claim 1 + 完整全文/圖說**,依法域選來源：
   - **TW 案**:`gpss_search(pub_number="TW...", databases=["TWA","TWB"])`。
   - **US/EP/WO/JP/CN/KR/… 案(非 TW)**:`google_get_patent_claims(...)` + `google_get_patent_description(...)`(BigQuery 合法 API,回全部請求項 + 完整說明書含 BRIEF DESCRIPTION OF THE DRAWINGS 逐圖文字說明)。
   - **US 案次選**:`uspto_patents(method="ppubs_get_full_document", guid=...)`。
6. **代表圖(圖檔影像)**：優先呼叫 `gpss_download_representative_figure` (TW 案優先，見 §5 與 `../reference/priorsearch/pdf-figure-extraction.md`) 取得絕對圖檔網址並完成下載。

### D. 交付物產出 → `99_deliverables/`
7. **Excel 專利池**(`xlsx` skill / openpyxl):書目主表(格式化/autofilter/凍結首列/三地色票)+ 統計分頁(國別/情境/IPC/年份)。產出後 **LibreOffice recalc** 驗證零錯誤。
8. **技術洞察報告 DOCX**(docxmcp **Mode A**,組 package 於 `04_report/`):流程見 `../reference/priorsearch/docx-assembly.md`,**probe 驗證 `ok=True` 才算交付**。報告章節見 §4。

## 4. 報告章節(§1 為使用者強制要求)

- **§1 檢索方法與可復現步驟**(必含,讓後續 AI 能復現並改良):引擎與來源優先序、三地資料庫代碼、IPC/CPC 分類錨點、三地關鍵字矩陣。**必須以 Markdown 結構化表格詳細記錄每一則檢索的查詢條件式、使用的資料庫來源、以及回傳的結果數量**。內容直接取自 `00_campaign.md` + `01_search/matrix-log.md`。
- §2 專利池全局分佈(嵌統計圖表)
- §3 各情境技術洞察(白話套路 + 差異化主軸)
- **§4 重點前案細部分析**(針對所有評等為 5 級的專利)：包含書目資料、逐字 Claim 1、代表圖與附圖文字說明，以及「**白話技術解析**」區塊。該解析必須在充分理解 Claim 請求項內容後，以白話文重新闡述並回答四個核心問題：
  1. 主要解決什麼問題。
  2. 採用了什麼技術手段/方法。
  3. 獲得專利的獨到關鍵點是哪個步驟或核心技術（新穎性特徵）。
  4. 對於實作「目標產品/開發主題（例如：長照智慧家庭）」的產品開發有什麼啟發與具體建議。
- §5 策略建議
- §6 檢索限制與誠實缺口

## 5. 原始專利 PDF / 代表圖

- **能力現況**(實證):見 `../reference/priorsearch/pdf-figure-extraction.md`。摘要——文字(claims/description/圖說)走 `google_*` BigQuery + GPSS/USPTO PPUBS;**原始 PDF/圖檔**走 `fetch_patent_pdf` 統一工具(已實作、端到端驗證,含 TW 案)。
- **原始 PDF 的合法取得**:針對 shortlist 的**已知專利號**,逐件呼叫 `fetch_patent_pdf(publication_number="<PN>")` → 內部依序試 `epo_images`(EPO OPS 官方影像 API)→ `google_citation`(從專利頁解析真實雜湊 `citation_pdf_url` 再下載)。回 docxmcp 風格 token handle,把 token 交給 docxmcp `decompose(format=pdf)` 抽圖,圖檔落 `03_assets/patents/`。**這是「針對已知專利的逐件下載」,非批量爬取**——量小、目標明確、合法。⚠️ 不要自己拼 `/pdfs/<PN>.pdf`(錯誤路徑,GCS 回 403);真實 URL 是帶雜湊的 `/xx/yy/zz/<hash>/<PN>.pdf`,由工具自動解析。SOP 見 `pdf-figure-extraction.md`。
- **取不到圖檔影像時**:以「逐字 Claim 1 + 附圖文字說明」(§3-C)替代,並在報告 §4/§6 誠實標註。

## Token 紀律
探針只取必要欄;巨量召回由子代理落地 `01_search/raw/`、不回主 context;完整 claims/全文只對 shortlist 取;每讀一篇蒸餾成 ~50 token 寫回 `candidates.csv`。
