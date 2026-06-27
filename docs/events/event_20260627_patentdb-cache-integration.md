# Event: PatentDB Local Cache & Retrieval Integration

## 需求背景
目前專利下載工具仍每次連網請求，且下載檔案只存於暫存 token 區，未能有效利用本地建立的 `patentdb/` 專利庫。我們需要實作本地提取優先（Read-Through）與下載後自動存入本地庫（Write-Through）的配套機制，以實現真正的本地快取專利庫。

## 範圍 (Scope)

### IN
1. **本地優先讀取 (Read-Through)**：
   - 在 `fetch_patent_pdf` 與 `gpss_download_patent_xml` 中，先將專利號正規化，並根據國別判定本地 `patentdb/` 是否已有該 PDF/XML 檔案。若有，直接加載至 `token_store` 並返回。
2. **下載後自動存入本地庫 (Write-Through)**：
   - 聯網下載成功後，自動將檔案備份至 `patentdb/` 對應的標準路徑，以防未來重複檢索。
3. **自動生成簡易 `metadata.json`**：
   - 下載成功後，若本地沒有 `metadata.json`，自動將基本的書目欄位（如專利號、下載時間等）寫入 `metadata.json` 作為佔位元。

### OUT
- 不在本階段處理歷史下載暫存檔（token 區）的追溯同步。

## 任務清單
- [ ] 在 `patents.py` 實作本地快取查詢與寫入輔助函式。
- [ ] 修改 `fetch_patent_pdf` 與 `gpss_download_patent_xml` 引入快取讀寫。
- [ ] 撰寫單元測試驗證「本地快取命中時不發起 HTTP 請求，直接回傳本地檔案」。
- [ ] 執行測試與驗證。
