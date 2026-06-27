# Event: GPSS PDF Download Feature Expansion

## 需求背景
使用者希望擴充現有「利用 GPSS 下載代表圖」的會話模擬機制，使其具備下載台灣專利原檔 PDF 的能力。此舉有助於填補台灣專利原檔在 `epo_images` 或 `google_citation` 下載管道的缺失。

## 範圍 (Scope)

### IN
1. **新增 `gpss_download_patent_pdf` 原生工具**：
   - 接受 `publication_number`，模擬 GPSS 登入與檢索會話。
   - 從詳細頁面提取所有 `harder` 下載連結，優先選取含有 `TWBA` 或 `TWBP` 的說明書 PDF。
   - 若不存在前述說明書，則使用第一個可用的說明書 PDF。
   - 發送請求取得該 PDF 位元組資料，儲存至 `token_store`。
2. **擴充 `fetch_patent_pdf` 工具的 sources 降級鏈**：
   - 將 `gpss_pdf` 納入可選與預設的 sources 降級鏈。預設順序調整為 `["epo_images", "gpss_pdf", "google_citation"]`。
   - 若為台灣專利（如 `TW` 前綴），將自動優先或適用此路由。
3. **新增 `gpss_download_patent_xml` 原生工具**：
   - 接受 `publication_number`，模擬 GPSS 會話。
   - 從詳細頁面中找到對應「公告/公開全文」的 `TW_GX` 連結。
   - 請求 `TW_GX` 的連結以取得含有 Refresh 跳轉至 `dc.xml` 的 HTML。
   - 解析出真正 `dc.xml` 的下載路徑，發送 GET 請求取得結構化 XML 全文。
   - 將 XML 全文二進位資料儲存至 `token_store` 中，並回傳 Handle。

### OUT
- 不處理非 PDF 格式的說明書網頁（僅抓取說明書 PDF 的二進位檔案）。
- 不提供非台灣專利在 GPSS 中的專利說明書 PDF 下載。

## 任務清單
- [x] 撰寫 `gpss_download_patent_pdf` 工具並註冊於 `patents.py`。
- [x] 整合 `gpss_pdf` 降級路由至 `fetch_patent_pdf` 中。
- [x] 撰寫單元測試驗證 GPSS PDF 下載。
- [x] 進行端到端冒煙測試（使用 TWI854998B 等台灣專利）。
- [ ] 撰寫 `gpss_download_patent_xml` 工具並註冊於 `patents.py`。
- [ ] 撰寫單元測試驗證 GPSS XML 下載。
- [ ] 同步修改 `specs/` 相關文件。
