# Spec: remediation_drawing-scraping-cdn

## Purpose

固化 BR_20260628 六項代表圖取得修復進 patentmcp 工具層與 companion skill，使代表圖流程在 Cloudflare challenge、CDN 403、EPO 單頁、掃描版 PDF 等失敗情境下，行為可靠、可觀測、可降級且不違反爬蟲天條。

## Requirements

### Requirement: GPSS 抓圖單線程節流 (A)

#### Scenario: 並發呼叫多個 GPSS 抓圖工具
- **GIVEN** 同時發起多個 `gpss_download_*` 工具呼叫
- **WHEN** 它們競爭存取 `tipo.gov.tw`
- **THEN** 所有對該站的請求被同一把 module-level `asyncio.Lock` 序列化（任一時刻僅一個進行）
- **AND** 每個請求在實際 HTTP 動作前等待 `random.uniform(GPSS_MIN_DELAY, GPSS_MAX_DELAY)` 秒（預設 1.0~3.0）

#### Scenario: 環境變數調節節流
- **GIVEN** 設定 `GPSS_SCRAPE_MIN_DELAY=0.5` 與 `GPSS_SCRAPE_MAX_DELAY=1.5`
- **WHEN** 抓圖工具執行
- **THEN** 延遲區間採用環境變數值

### Requirement: Google CDN 403 顯式降級 (B)

#### Scenario: 下載新案縮圖遭防盜鏈
- **GIVEN** `gpatents_download_figure` 對 patentimages CDN 發出請求
- **WHEN** CDN 回 403 Forbidden
- **THEN** 回傳 `{success: False, error: "CDN_FORBIDDEN", downgrade_hint: "use extract_representative_figure (PDF pipeline)", url: <url>}`
- **AND** 不在工具內自動重試或自動轉抓（交呼叫端決策）

### Requirement: extract_representative_figure 高階工具 (D)

#### Scenario: 標準向量 PDF 取代表圖
- **GIVEN** 一個含說明書附圖的專利 PDF（透過 fetch_patent_pdf 取得）
- **WHEN** 呼叫 `extract_representative_figure(publication_number)`
- **THEN** 工具用 `pdftotext` 逐頁定位首個 `FIG. 1`/`图1`/`圖1` 頁（跳過第 1 頁封面）
- **AND** 用 `pdftoppm -r 200 -png` 渲染該頁
- **AND** 回傳 PNG 的 token handle {token, rel, download_url, bytes, sha256, page_number}

#### Scenario: 掃描版 PDF 無文字層
- **GIVEN** 一個純影像掃描版 PDF（pdftotext 抽不到文字）
- **WHEN** 呼叫 extract_representative_figure
- **THEN** fallback 到 reference-numeral 密度最高頁；若仍無法定位，回 `{success: False, error: "NO_FIGURE_PAGE"}`
- **AND** 不亂選最大檔案頁

### Requirement: 縮圖解析度警語 (E)

#### Scenario: gpatents_search 回傳縮圖 URL
- **GIVEN** `gpatents_search` 命中含 thumbnail 的結果
- **WHEN** 結果經 `_flatten` 整理
- **THEN** 每筆帶 `representative_figure_resolution: "thumbnail"`（當 thumb 存在）
- **AND** companion skill 明文警告縮圖不可用於報告嵌入

### Requirement: EPO 單頁著錄摘要偵測降級 (F)

#### Scenario: CN/TW 案 EPO 只回著錄摘要
- **GIVEN** `fetch_patent_pdf` 經 epo_images 取得 PDF bytes
- **WHEN** `pdfinfo` 判定頁數 ≤ 1
- **THEN** 記 attempt `{source: "epo_images", ok: False, error: "EPO_BIBLIO_ONLY_1PAGE", pages: 1}`
- **AND** continue 到下一來源（gpss_pdf / google_citation）而非落地著錄摘要當代表圖

## Acceptance Checks

- [ ] 並發 3 個 GPSS 抓圖呼叫，觀測到序列化（lock）與每次 1~3s 延遲（可用 monkeypatch 計時驗證）。
- [ ] `gpatents_download_figure` 對 mock 403 回 `CDN_FORBIDDEN` 結構。
- [ ] `extract_representative_figure` 對含 FIG.1 的測試 PDF 回正確 page_number 與 PNG handle。
- [ ] `extract_representative_figure` 對無文字層 PDF 回 `NO_FIGURE_PAGE`，不誤選。
- [ ] `gpatents_search` `_flatten` 結果含 `representative_figure_resolution`。
- [ ] `fetch_patent_pdf` 對 mock 單頁 EPO PDF 記 `EPO_BIBLIO_ONLY_1PAGE` 並 continue。
- [ ] `import patent_mcp_server.patents` smoke test 通過。
