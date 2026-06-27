# Implementation Spec: Patent PDF & Figure Retrieval

## 1. 模組擴充規格

### 1.1 EPO Client (`epo/client.py`)
- **`_get_binary(url, params)`**: 支援非 JSON 回傳，維持 OAuth 與 pacing 邏輯。
- **`get_image_metadata(docdb_id)`**: 調用 `/published-data/publication/docdb/{id}/images`。
- **`download_full_pdf(id)`**: 根據 metadata 逐頁取得 `fullimage.pdf` 並在記憶體或暫存區合併。

### 1.2 Google Client (`gpatents/client.py`)
- **`resolve_citation_url(pub_number)`**: 
  - 請求 `https://patents.google.com/patent/{pub}/en`。
  - 提取 `citation_pdf_url`。
- **`download_from_url(url)`**: 帶正確 UA 執行二進位下載。

### 1.3 MCP Tooling (`patents.py`)
- **`fetch_patent_pdf`**:
  - 參數：`publication_number`, `priority=['epo', 'uspto', 'google']`。
  - 邏輯：按優先序嘗試，成功後存入 token store 並回傳 handle。

## 2. 檔案目錄與存儲
- 暫存目錄：`vendor/patents-mcp/data/temp/`
- 產出目錄：對齊 `token-store` 配置（通常為 `/tmp/patents-mcp-tokens/`）。

## 3. 驗證機制
- 驗證 PDF 檔頭 (`%PDF`)。
- 整合測試腳本：`scripts/test_pdf_fetch.py`。
