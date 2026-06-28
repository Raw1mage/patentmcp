# Spec: gpss-session-reuse-batch

## Purpose

讓 GPSS 批量抓圖在一個 batch 內共用單一瀏覽 session(單一 httpx.AsyncClient + 持續 cookie jar),單線排隊、握手一次、逐筆復用 cf_clearance,並修正 batch 非 TW 分支必定失敗的 bug。

## Requirements

### Requirement: 全批共用單一 GPSS session

#### Scenario: batch 抓圖握手只做一次
- **GIVEN** 一組 N 筆專利公開號傳入 `patentmcp_batch_download_figures`
- **WHEN** batch 開始執行
- **THEN** 取得 `_GPSS_SCRAPE_LOCK` 一次
- **AND** 建立單一 `_GpssScrapeSession`,執行 portal + GPSS init 握手「一次」
- **AND** 後續每筆專利在同一 session 上抓圖,cookie jar 全程累積不重置
- **AND** batch 結束時關閉該 session(client.aclose())

#### Scenario: 逐筆之間單線排隊 + 隨機延遲
- **GIVEN** session 已開啟
- **WHEN** 處理第 2 筆(含)以後的專利
- **THEN** 每筆之前呼叫 `_gpss_scrape_pace()` 隨機延遲(GPSS_SCRAPE_MIN_DELAY ~ MAX_DELAY)
- **AND** 任一時刻只有一個請求在飛(Concurrency=1,由 LOCK 保證)

### Requirement: 修正 batch 非 TW 分支取圖路徑

#### Scenario: 非 TW 專利走報告級 PDF pipeline
- **GIVEN** 一筆非 TW(如 US/CN)專利公開號
- **WHEN** batch 處理該筆
- **THEN** 改呼叫 `extract_representative_figure(pub)`(PDF → FIG.1 → 高 DPI PNG)
- **AND** 不呼叫 `get_patent()` 取 `representative_figure_url`(該欄位不存在於 get_patent 回傳)
- **AND** 不使用 60x80 縮圖(BR_20260628 §2 天條 #3 禁止)

#### Scenario: TW 專利走 GPSS 代表圖
- **GIVEN** 一筆 TW 專利公開號
- **WHEN** batch 處理該筆
- **THEN** 走 GPSS 代表圖路徑(在共用 session 上)

### Requirement: 單筆工具對外契約不變

#### Scenario: 單筆 GPSS 工具仍可獨立呼叫
- **GIVEN** 直接呼叫 `gpss_download_representative_figure(pn)` 或 `gpss_download_patent_pdf(pn)`
- **WHEN** 工具執行
- **THEN** 回傳 docxmcp 式 handle,與重構前相同
- **AND** 底層使用同一 session helper(size=1 的 open→fetch→close)
- **AND** 仍受 `_GPSS_SCRAPE_LOCK` 保護

### Requirement: 失敗顯式化,無 silent fallback

#### Scenario: 某筆失敗不影響其他筆
- **GIVEN** batch 中某筆抓圖失敗(404 / 無圖 / 503)
- **WHEN** 該筆失敗
- **THEN** 記入 `skipped[pub]` 帶 explicit reason
- **AND** 503/quota/unavailable 類錯誤加入 cooldown skip list
- **AND** session 不中斷,繼續處理下一筆

## Acceptance Checks

- [ ] batch 對 US/CN 案不再回 "No representative figure URL found"
- [ ] batch 全程只建立一個 httpx.AsyncClient(可由測試 mock 計數驗證)
- [ ] 單筆工具回傳結構與重構前一致
- [ ] 既有 9 個 BR_20260628 測試仍全綠
- [ ] 新增 batch 兩分支 + session 復用測試通過
