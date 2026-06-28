# Observability: remediation_drawing-scraping-cdn

## Events

| 訊號 | 來源工具 | log level | 用途 |
|---|---|---|---|
| `GPSS scrape acquired lock, sleeping {d:.2f}s` | GPSS 抓圖三工具 (A) | DEBUG | 確認序列化與節流實際生效 |
| `Google Patents CDN 403 (blocked). Downgrade to PDF pipeline.` | gpatents_download_figure (B) | WARNING | 區分防盜鏈 vs 一般失敗 |
| `extract_representative_figure: FIG.1 located at page {n} via {method}` | extract_representative_figure (D) | INFO | 追溯定位頁與方法 (fig1_text / refnum_density_fallback) |
| `extract_representative_figure: NO_FIGURE_PAGE for {pn}` | extract_representative_figure (D) | WARNING | 掃描版/無附圖明確失敗 |
| `EPO image PDF for {pn} has {pages} page(s) — biblio-only, downgrading` | fetch_patent_pdf (F) | WARNING | CN/TW 單頁著錄摘要降級 |

## Metrics

（建議追蹤，非本次強制實作）

- `gpss_scrape_lock_wait_seconds`：抓圖排隊等待時間（觀測序列化壅塞）。
- `figure_extract_success_ratio`：extract_representative_figure 成功 / 總呼叫。
- `cdn_403_downgrade_count`：CDN 403 降級次數（觀測 Google 防盜鏈強度）。
- `epo_biblio_only_count`：EPO 單頁降級次數（觀測 EPO 對 CN/TW 覆蓋）。

## Invariants（可觀測保證）

- **INV-1**：任一時刻對 `tipo.gov.tw` 的抓圖 HTTP 請求數 ≤ 1（單線程天條）。違反訊號：log 出現重疊的 acquire 而無對應 release。
- **INV-2**：`extract_representative_figure` 回傳的 `page_number` 必 ≥ 2（跳過封面），除非 PDF 僅 1 頁有效附圖。
- **INV-3**：`EPO_BIBLIO_ONLY_1PAGE` 的 PDF 永不落地為代表圖來源。
- **INV-4**：`CDN_FORBIDDEN` 後工具不自動重試（無連續 403 retry log）。

## Debug Map

- 抓圖序列化邊界：`patents.py` `_GPSS_SCRAPE_LOCK` acquire/release log。
- PDF 頁面定位邊界：`extract_representative_figure` 的 pdftotext 逐頁掃描 log。
- 來源降級邊界：`fetch_patent_pdf` 的 `attempts[]` trace（include_attempts=True 時返回）。
- 限流退避邊界（既有）：`gpatents/client.py` `_get` 的 cooldown log。
