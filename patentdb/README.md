# Local Patent Database (PatentDB) Specification

本目錄為本地端專利資料庫 (`patentdb/`)，旨在積累與儲存已檢索的專利資料，以減少重複上網檢索的 API 呼叫與頻寬成本。

## 雙層架構（Two-Layer）

patentdb 由兩層構成，職責分離：

| 層 | 實體 | 角色 |
|---|---|---|
| **結構化層** | `patentdb.sqlite` | 全域書目事實的統一資料庫——一件專利一列、可全文檢索（FTS5）、跨專案複用、可承載百萬級書目量 |
| **實體 blob 層** | `<國別>/<正規化號>/` | 專利原檔（PDF/XML/figures）+ `metadata.json`，由下載工具 write-through 落地 |

兩層共用 `pubno`（正規化公開號）為鍵：sqlite 存書目欄位 + blob 路徑/sha256；檔案系統存實體本體。

### 結構化層 sqlite（patentdb.sqlite）

- **`patents` 表**：全域書目（pubno PK + 國別/標題/摘要/claim1/CPC/IPC/申請人/發明人/日期/family + blob 路徑 + acquisition_cost）。
- **`patents_fts`**：FTS5 全文（標題/摘要/claim1，trigram tokenizer 支援 CJK；2 字 CJK 詞自動走 LIKE fallback）。
- **無 screening 評分表**：相關性評分是 by-project 產物，留在各專案的 `candidates.csv`，不污染全域書目唯一真相。
- 工具：`patentdb_put`（漸進 upsert）/ `patentdb_query`（pubno 精查 / FTS / country 過濾）/ `patentdb_import_csv`（candidates.csv 批次入庫，只書目）。

### 收集哲學（被動累加 + 成本加權）

- **被動累加**：所有書目/blob 欄位 nullable、可後補；register 不要求完整；upsert 漸進合併（COALESCE 既有非空，不覆寫）。一件專利可只有 pubno + 標題先入庫，日後再補 claim/圖。
- **成本加權收集**：`acquisition_cost` 粗分 `high`/`low`/`free`。**貴的（BigQuery/EPO/同意爬取）取得一次絕不重抓**；免費可再生的（GPSS REST 書目）不強制囤，順手取得才入庫（邊際成本為零）。收集基本常用資訊以加速日常工作，不刻意撈偏門冷僻的東西浪費資源。
- **落地即吸收**：`build_screening_table` 拿到 CSV 的當下即 inline 吸收書目進 sqlite（零額外 toolcall、零網路）；下載工具下載成功即 register blob+書目。養庫平行於專案工作、不勞煩 AI。
- **腳踏兩條船**：專案分析時除了用本案 search 檔案，並行 `patentdb_query` 查全域庫，把本案沒撈到但適合的標的一併納入報告——庫越大、新案越省 quota、覆蓋越廣。

## 實體 blob 層目錄結構設計

為確保目錄的高可讀性、泛用性以及機器自動化檢索效率，專利庫採用以下兩級分層的資料夾結構：

```text
patentdb/
├── README.md                  # 本設計規範文檔
└── [Country]/                 # 第一級：國家/組織代碼 (例如 TW, US, EP, WO)
    └── [Normalized_No]/       # 第二級：正規化專利號 (例如 I854998, 202412345)
        ├── metadata.json      # 專利基本書目詮釋資料
        ├── specification.pdf  # 專利原檔說明書 PDF (必備/泛用來源)
        ├── specification.xml  # 結構化說明書全文 XML (若來源支持)
        └── figures/           # 圖式/附圖目錄 (選填，由 PDF/XML 抽出的圖片)
            ├── TWG1.png       # 代表圖
            ├── 00001.png      # 附圖 1
            └── 00002.png      # 附圖 2
```

## 檔案契約說明

### 1. `metadata.json`
存放專利書目的結構化 Metadata，統一使用 UTF-8 編碼。欄位範例如下：
* `publication_number`: 專利公開/公告號（如 TWI854998B）。
* `title`: 專利名稱（可包含多語系，如 `tw`, `en`）。
* `application_number`: 申請號。
* `application_date`: 申請日 (YYYYMMDD)。
* `publication_date`: 公開/公告日 (YYYYMMDD)。
* `inventors`: 發明人清單。
* `applicants`: 申請人清單。
* `abstract`: 專利摘要。
* `cpc_codes`: CPC 分類號。
* `ipc_codes`: IPC 分類號（選填）。

### 2. `specification.pdf`
專利原檔 PDF。多數專利局均會提供此格式，為本地專利庫最泛用的基礎儲存格式。

### 3. `specification.xml`
若檢索管道（如 TIPO GPSS 的 `dc.xml`）支援結構化 XML 下載，則儲存於此。其內容包含結構化純文字的說明書本文與申請專利範圍（claims），可供系統直接解析，無須再進行 PDF 的文字與表格抽取。

### 4. `figures/`
存放由該專利中解析或提取出來的圖式與附圖檔案。
