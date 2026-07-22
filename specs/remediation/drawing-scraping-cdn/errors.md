# Errors: remediation_drawing-scraping-cdn

## Error Catalogue

每個錯誤碼皆為**顯式結構化訊號**，非靜默 fallback（天條 11）。

| Code | Tool | Message / 條件 | Recovery 策略 | 責任層 |
|---|---|---|---|---|
| `CDN_FORBIDDEN` | gpatents_download_figure | patentimages CDN 回 403（新案防盜鏈） | 回 `downgrade_hint`，呼叫端改走 `extract_representative_figure`（PDF pipeline） | 工具層 (B) |
| `NO_FIGURE_PAGE` | extract_representative_figure | PDF 內找不到 FIG.1 頁，且 reference-numeral fallback 也失敗（多為掃描版無文字層） | 明確失敗；呼叫端可人工指定頁或改用其他來源；不亂選最大檔案頁 | 工具層 (D) |
| `NO_PDF` | extract_representative_figure | fetch_patent_pdf 全來源失敗，無 PDF 可分解 | 回報無可用 PDF；呼叫端決定是否換 publication_number 或來源 | 工具層 (D) |
| `RENDER_FAILED` | extract_representative_figure | pdftoppm 渲染目標頁失敗（PDF 損毀 / poppler 錯誤） | 回報 stderr 摘要；呼叫端可重取 PDF | 工具層 (D) |
| `EPO_BIBLIO_ONLY_1PAGE` | fetch_patent_pdf (epo_images) | EPO OPS 對 CN/TW 只回單頁著錄摘要（pdfinfo Pages ≤ 1） | 記 attempt 並 continue 到 gpss_pdf / google_citation，不落地著錄摘要當代表圖 | 工具層 (F) |

## 既有錯誤碼（沿用，不改）

| Code | Tool | 說明 |
|---|---|---|
| `EPO_NOT_CONFIGURED` | fetch_patent_pdf | EPO client 未設定 OAuth |
| `NO_IMAGES` | fetch_patent_pdf | EPO images 查詢 count==0 |
| `EMPTY_PDF` | fetch_patent_pdf | 來源回空 bytes |
| `ALL_SOURCES_FAILED` | fetch_patent_pdf | 所有來源皆失敗 |
| `THROTTLED` | gpatents resolve_pdf_url | Google 429/503 限流 |

## 反模式（禁止）

- 不得將 `EPO_BIBLIO_ONLY_1PAGE` 的單頁 PDF 渲染後當代表圖插入報告。
- 不得在 `CDN_FORBIDDEN` 後於工具內自動重試或自動轉抓其他 URL（須交呼叫端決策）。
- 不得在 `NO_FIGURE_PAGE` 時退回「選最大檔案頁」策略。
