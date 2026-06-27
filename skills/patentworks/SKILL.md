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
   - **① GPSS**(`gpss_search`,**首選**)——TIPO 官方 REST,一次回 PN/AN/標題/摘要/Claim1/CPC/IPC/申請人/日期,IPC 錨定,一站涵蓋 US/CN/TW。逐字 Claim 1 用 `gpss_search(pub_number=...)` 單號查詢三地通用。
   - **② EPO OPS**(`epo_family` 官方 INPADOC 家族 / `epo_biblio` 摘要 / `epo_search` CQL)——歐洲專利局官方 API。**⚠️ 流量限制與計費安全說明**：(1) **免費額度為每週 4 GB**，若超過該流量，API 會直接阻斷連線 (通常返回 HTTP 403 / Quota Exceeded) 而**不會自動扣款**，故無意外產生帳單的風險（若要無限流量需主動付年費 €2,800/年）；(2) 有每 IP 每分鐘約 10 次搜尋的頻率限制，批次呼叫時需做好節流。
   - **③ USPTO PPUBS**(`uspto_patents`)——美國案完整全文 + 附圖文字說明用 `method="ppubs_get_full_document"`。
   - **④ Google Patents BigQuery(`google_*`)——合法註冊 API,不是爬蟲,別跟 `gpatents_*` 混為一談**。走 `GOOGLE_APPLICATION_CREDENTIALS` service account 查 `patents-public-data` 公開資料集(ToS 乾淨、不被限速封鎖)。實測 `google_get_patent_claims` / `google_get_patent_description` 對 US 案乾淨回傳**全部請求項 + 完整說明書全文(含 BRIEF DESCRIPTION OF THE DRAWINGS 逐圖文字說明)**。涵蓋 US/EP/WO/JP/CN/KR/GB/DE/FR/CA/AU(**不含 TW**,TW 走 ①GPSS)。**⚠️ 計費與成本風險警告**：由於 BigQuery 是按查詢掃描的資料欄位量計費，執行模糊檢索（如 `google_search_*`）會對巨大公開資料表進行全表掃描，極易爆出高額帳單（曾有單次檢索累積達 10 TB 掃描量而產生約 60 美金費用的案例）。**防護機制**：(1) 系統已在 `config.py` 限制單次查詢掃描量上限為 10 GB (`BIGQUERY_MAX_BYTES_BILLED=10737418240`)，超量查詢會被自動阻斷並報錯；(2) 建議透過 GCP CLI 限制專案的每日查詢上限（例如 `gcloud alpha services quota update --service=bigquery.googleapis.com --consumer=projects/YOUR_PROJECT_ID --metric=bigquery.googleapis.com/quota/query/usage --unit="1/d/{project}" --value=10240 --force`）以維持在每月 1 TB 的免費額度內。**限制**:只有文字(claims/description/書目),**沒有圖檔影像**;適合單號精確取文(`get_patent*`)，大批量全文掃描應極力避免。
   - **⑤ Google Patents 網頁爬蟲(`gpatents_*`)——最後手段**。`gpatents_*`(`gpatents_search`/`gpatents_get`/`gpatents_download_*`)爬 patents.google.com 網頁,**非官方、極易被限速封鎖(實測連續 timeout / storage 403 / 頁面 503)**。只在 ①②③④ 都填不了某欄位時才用(它獨有的是 `representative_figure_url` 代表圖縮圖),且須預期失敗、設早退(連 3 次失敗即放棄)。**切勿委派子代理去吸收會 timeout 的 `gpatents_*` 輸出**——子代理會反覆 `worker_dead`。
   - ⚠️ **`google_*`(BigQuery 合法 API)≠ `gpatents_*`(網頁爬蟲)**:工具名都含 "google" 但後端與合法性完全不同。要逐字 claims / 全文 / 圖說,優先用 `google_get_patent*`(④),不要因為名字有 google 就避開。
   - PDF 二進位下載端點(`gpatents_download_pdf` / `uspto ppubs_download_patent_pdf`)本部署實測**系統性故障**;但**原始附圖的文字說明**可由 ④`google_get_patent_description` 或 ③USPTO PPUBS 可靠取得。原始圖檔影像不可得時走 `reference/priorsearch/pdf-figure-extraction.md` 的降級路徑。

## 領域骨幹

人類從業流程與 AI 對應見 `../patent-practitioner-workflow.md`。

## 專利工作池資料樹規範 (Data Tree Specification)

為了確保專利檢索、統計圖表繪製、報告編譯 (docxmcp) 之間的資料流一致性，各專案工作目錄的中間產物必須遵守以下資料樹規範，並與 `docxmcp` 的 `manifest` 結構調和：

### 1. 目錄結構
每一個專案的工作池目錄應包含以下核心檔案與子目錄：
```
<project_dir>/
├── manifest.json              # 資料池與產出物 manifest 設定檔 (與 docxmcp 調和)
├── candidates.csv             # 結構化專利候選池 (包含 20 篇以上專利)
├── build_xlsx.py              # 生成與美化 Excel 專利表腳本 (使用 openpyxl)
├── build_charts.py            # 繪製統計圖表腳本 (使用 matplotlib)
├── build_docx_pkg.py          # 打包為 docxmcp Mode-A 包的腳本
├── build_html.py              # 生成 HTML 預覽報告的腳本
├── <project_name>_技術洞察報告.md   # 技術洞察報告原始 Markdown 檔案 (SSOT)
├── <project_name>_技術洞察報告.docx # 最終經由 docxmcp 產出的 Word 報告
└── assets/
    └── figures/               # 存放 build_charts.py 所繪製的 5 張統計圖表 (PNG)
```

### 2. 中間產物 Manifest 規範 (`manifest.json`)
資料池的 `manifest.json` 必須定義資料的格式與各檔案對應，以與 `docxmcp` 格式調和：
```json
{
  "format": "patent_pool",
  "project": "專案名稱",
  "version": "rN",
  "candidates": "candidates.csv",
  "raw_data": "raw_patents.json",
  "claims_store": "us_claims.json"
}
```

### 3. 專利資料庫格式 (`candidates.csv`)
統一欄位格式，欄位順序如下：
`#,類別,代表專利號,申請人,優先權,國別,標題,推測CPC,相關性(1-5級),技術要點(蒸餾),命中要件,家族成員,連結,人工複核`

### 4. 統計圖表與命名
`build_charts.py` 生成的統計圖表必須固定命名與用途，以便 Markdown 與 Word 報告穩定引用：
*   `assets/figures/fig1_country.png` - 專利國別分佈直方圖
*   `assets/figures/fig2_scenario.png` - 專利相關性分佈直方圖 (取代原情境分佈)
*   `assets/figures/fig3_ipc.png` - 主要 CPC 分類分佈橫向條形圖
*   `assets/figures/fig4_smarthome.png` - 專利清單類別佔比圓餅圖
*   `assets/figures/fig5_year.png` - 專利優先權年份分佈折線或條形圖

