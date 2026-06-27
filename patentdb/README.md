# Local Patent Database (PatentDB) Specification

本目錄為本地端專利資料庫 (`patentdb/`)，旨在積累與儲存已檢索的專利資料，以減少重複上網檢索的 API 呼叫與頻寬成本。

## 目錄結構設計

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
