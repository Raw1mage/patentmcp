# Tasks: br20260628_tooling_skill_gpss_gaps

## 1. fetch_patent_pdf 顯式爬蟲 gate (BR③-A, DD-1)

- [x] 1.1 `fetch_patent_pdf` 加 `allow_scraping: bool = False` 參數;預設 False 時 gpss_pdf 來源被跳過,attempts 記 `SKIPPED_SCRAPING_NOT_AUTHORIZED`,全官方來源 miss 回 `SCRAPING_REQUIRED`
- [x] 1.2 同步內部呼叫端:`extract_representative_figure`、`patentmcp_batch_download_figures` 改傳 `allow_scraping=True`
- [x] 1.3 更新 `fetch_patent_pdf` docstring 反映新 gate 行為
- [x] 1.4 驗證:純 TW 案預設回 SCRAPING_REQUIRED;allow_scraping=True 才抓

## 2. 參數命名統一 (BR③-B, DD-2)

- [x] 2.1 `extract_representative_figure` / `patent_get_claim1` / `fetch_patent_pdf`:canonical `publication_number`,加 `patent_number` alias 解析
- [x] 2.2 `ppubs_batch_get_claims` / batch 工具:canonical `publication_numbers`,加 `patent_numbers` alias
- [x] 2.3 驗證:每工具用舊名 + 新名各呼叫一次都通(向後相容)

## 3. extract_representative_figure 失敗分級 (BR③-C, DD-3)

- [x] 3.1 `_locate_figure_page` 回 None 時探測 PDF image XObject 數
- [x] 3.2 image_count>0 → 回 `NO_FIGURE_PAGE_BUT_IMAGES_PRESENT`(帶 image_count/pages/建議);=0 → 維持 `NO_FIGURE_PAGE`
- [x] 3.3 驗證:掃描版 PDF(US20230081319A1 類)回 image_count 而非裸 NO_FIGURE_PAGE

## 4. ppubs_get_full_document 便利包裝 (BR③-D, DD-4)

- [x] 4.1 dispatcher:method=ppubs_get_full_document 未給 guid/source_type 但給 publication_number 時,複用 ppubs_get_patent_by_number 的 pub→guid 解析再取全文
- [x] 4.2 更新 docstring
- [x] 4.3 驗證:`ppubs_get_full_document(publication_number=...)` 一次取得全文

## 5. GPSS claim1 空旗標 (BR①-D, DD-5)

- [x] 5.1 `gpss_to_records` 偵測 claim1 空或剝樣板前綴後無內文 → record 加 `claim1_empty: true`
- [x] 5.2 驗證:US 空 claim 案 record 帶 claim1_empty=true

## 6. 偵查後決策:uspc / family (BR①-B/C, DD-6)

- [x] 6.1 webfetch 查 TIPO GPSS API 官方文件,確認後端有無 US 分類欄位代碼
- [x] 6.2 [?] 依規格結果決策:支援→gpss_search 加 uspc 參數;不支援→skill 記載 uspto_patents CCL 樣板
- [x] 6.3 family:評估啟發式分群可行性 or skill 記載「GPSS 去重=公開號級」限制

## 7. patentworks SKILL.md §5 更新 (BR②, C1/C2/C3)

- [x] 7.1 加「來源梯窮舉門檻(Exhaustion Gate)」硬規則
- [x] 7.2 全面更新工具清單:補載 fetch_patent_pdf / extract_representative_figure / patentmcp_batch_download_figures / ppubs_batch_get_claims;刪除過時「PDF 端點系統性故障」論斷
- [x] 7.3 重寫爬蟲天條天平:保留同意+限速,新增「同意後批量軟性機制是正規路徑,scraping:true 非違規」
- [x] 7.4 併入 Phase 6 的 uspc/family skill 記載結論

## 8. 收尾

- [x] 8.1 三份 BR 標記處理進度;BR① A(工具未 surface)轉記為 opencode side issue
- [x] 8.2 跑完整測試 suite + 同步 specs/architecture.md(或註記 No doc changes)
- [x] 8.3 event_record 收尾紀錄
