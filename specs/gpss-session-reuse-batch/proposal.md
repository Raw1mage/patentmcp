# Proposal: gpss-session-reuse-batch

## Why

- 使用者要批量抓代表圖,但 TIPO GPSS 前掛 Cloudflare WAF,平行請求會觸發 Managed Challenge → ReadTimeout。
- 現況雖有 `_GPSS_SCRAPE_LOCK` 單線鎖 + 隨機延遲(BR_20260628 A 已修),但**每筆專利都 `async with httpx.AsyncClient()` 新建 client**,等於每次丟掉 Cloudflare 的 `cf_clearance` cookie,並重走 portal→GPSS init→INFO token 全套握手。在 Cloudflare 眼中每次都是「全新可疑 client」,反而更易觸發挑戰 —— 這是 ReadTimeout 的更深層 RCA。
- 同時 `patentmcp_batch_download_figures` 非 TW 分支有 bug:呼叫 `get_patent()` 取 `representative_figure_url`,但該欄位只由 `search()._flatten()` 產生,`get_patent()` 從不回傳它,導致所有非 TW 專利落 else 分支回 "No representative figure URL found"。

## Original Requirement Wording (Baseline)

- "我需要批量進行的功能,但又不想要多併發觸發警報,寧願單線排隊,重複使用單一 session 慢慢工作"

## Requirement Revision History

- 2026-06-28: initial draft created via plan-init.ts
- 2026-06-28: 使用者確認 session 復用範圍 = 每個 batch 共用一個 session(非跨呼叫常駐)

## Effective Requirement Description

1. 批量抓代表圖時,整個 batch 共用單一 GPSS 瀏覽 session(單一 httpx.AsyncClient + 持續累積的 cookie jar),握手只做一次,逐筆復用 cf_clearance。
2. 全程單線排隊(維持 Concurrency=1),每筆之間隨機延遲。
3. 修正 batch 非 TW 分支 bug,改走報告級 PDF pipeline(`extract_representative_figure`),不走被禁的 60x80 縮圖。
4. 單筆 GPSS 工具行為對外不變。

## Scope

### IN
- 新增可復用的 GPSS scrape session 物件(持有單一 client + cookie jar;`open()` 一次握手;`fetch_figure(pn)` / `fetch_pdf(pn)` 逐筆復用)。
- `patentmcp_batch_download_figures` 改為:取鎖一次 → open session 一次 → for pn 逐筆抓 + pace → 全程同一 session;非 TW 改走 `extract_representative_figure`。
- 單筆 GPSS 工具(`gpss_download_representative_figure` / `gpss_download_patent_pdf`)重構為使用同一 session helper(size=1),行為不變。
- 補單元測試覆蓋 batch 兩條分支 + session 復用。

### OUT
- 跨多次 MCP 呼叫的常駐 session(使用者選每批一個 session)。
- docxmcp 跨容器 token 隔離(已由 host-pipe SOP 處理)。
- Cloudflare JS challenge 的真正瀏覽器執行(headless browser);仍維持 httpx 模擬。

## Non-Goals

- 不引入 Playwright/headless Chrome。
- 不改 GPSS 官方 REST API client(`gpss/client.py`)—— 那是合法 API,與抓蟲 session 無關。

## Constraints

- 天條:GPSS 抓圖是自製爬蟲,**永遠只准單線程順序執行 + 隨機延遲**。
- 天條:禁止新增 silent fallback;失敗要 explicit error。
- 不得用 representative_figure_url 縮圖交付。

## What Changes

- `patents.py`:新增 session 物件 / helper;重構三個抓圖工具與 batch 工具。

## Capabilities

### New Capabilities
- GPSS 可復用抓蟲 session:一個 batch 內握手一次、cookie 全程累積。

### Modified Capabilities
- `patentmcp_batch_download_figures`:全批共用 session;非 TW 走 PDF pipeline(修 bug)。
- `gpss_download_representative_figure` / `gpss_download_patent_pdf`:底層改用共用 session helper,對外契約不變。

## Impact

- 影響檔案:`src/patent_mcp_server/patents.py`、`tests/`。
- 對外 MCP 工具簽名不變;batch 對非 TW 案從「永遠失敗」變為「可用」。
