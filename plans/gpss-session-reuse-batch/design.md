# Design: gpss-session-reuse-batch

## Context

TIPO GPSS 抓圖是自製爬蟲(非合法 API),前掛 Cloudflare WAF。現況工具:
- `gpss_download_representative_figure` / `_impl`(patents.py:1730-1848)
- `gpss_download_patent_pdf`(patents.py:1851+)
- `patentmcp_batch_download_figures`(patents.py:2431-2509)
- 節流器 `_GPSS_SCRAPE_LOCK` + `_gpss_scrape_pace`(patents.py:80-88)

每個 `_impl` 內 `async with httpx.AsyncClient()` 自建 client,做完即關。

## Goals / Non-Goals

### Goals
- 一個 batch 內共用單一 httpx client(cookie jar 全程累積),握手一次。
- 修 batch 非 TW 分支 bug。
- 單筆工具對外契約不變。

### Non-Goals
- 跨呼叫常駐 session、headless browser。

## Decisions

- **DD-1**: 新增 `_GpssScrapeSession` 類別,持有單一 `httpx.AsyncClient`(headers/follow_redirects/timeout 與現況一致)。提供 `async open()`(portal + GPSS init 預熱,可選但保留擴充)、`async fetch_representative_figure(pn)`、`async fetch_pdf(pn)`、`async close()`。核心:把現有 `_impl` 內「自建 client」改成「接收注入的 client」。

- **DD-2**: 現有 `_gpss_download_representative_figure_impl` / `gpss_download_patent_pdf` 的 scrape 流程**整段搬進** session 方法,參數化 client。原本每筆重做的 portal→gpss2→INFO token,在 session 模式下,client 復用使得 Cloudflare cf_clearance cookie 持續有效。注意:GPSS 的 INFO token 是 per-search 的表單 token(每次搜尋仍需重新抓),但 **TCP/TLS 連線 + Cloudflare cookie** 復用才是抗 challenge 的關鍵。

- **DD-3**: `patentmcp_batch_download_figures` 重構:
  ```
  async with _GPSS_SCRAPE_LOCK:           # 整批一把鎖
      session = _GpssScrapeSession()
      try:
          for i, pub in enumerate(pubs):
              if i > 0: await _gpss_scrape_pace()   # 筆間延遲
              if pub.upper().startswith("TW"):
                  res = await session.fetch_representative_figure(pub)
              else:
                  res = await extract_representative_figure(pub)  # PDF pipeline
              ...cooldown/skip 邏輯不變...
      finally:
          await session.close()
  ```
  非 TW 改走 `extract_representative_figure`(PDF→FIG.1→高DPI PNG),修掉「get_patent 取不到 representative_figure_url」的 bug,且不踩被禁的縮圖。

- **DD-4**: 單筆工具 `gpss_download_representative_figure` / `gpss_download_patent_pdf` 改為:取鎖 → 建 size=1 session → pace → fetch → close。對外回傳結構不變。維持各自的 `_GPSS_SCRAPE_LOCK`(避免單筆與 batch 同時打 GPSS)。

- **DD-5**(修訂): 鎖的粒度 = **「每個 GPSS HTTP burst 一把鎖」**,而非整批持鎖。`_GpssScrapeSession` 的每個 fetch 方法 `async with _GPSS_SCRAPE_LOCK` 取鎖→pace→HTTP→釋放。batch 迴圈本身**不持鎖**。理由:(1) cookie 復用靠的是「單一持久 client」,與鎖的持有時間無關;(2) 整批持鎖會與下方 DD-7 的 re-entrant 路徑死鎖;(3) per-burst 鎖仍 100% 保證對 tiponet 的 Concurrency=1(同一 async task 內呼叫本就順序,跨 task 由鎖序列化)。

- **DD-6**: 非 TW 走 `extract_representative_figure` 不需 GPSS scrape session(它走 EPO/google_citation PDF chain;只有 EPO 失敗降級到 gpss_pdf 時才碰 GPSS,且走自己的 tool wrapper 取鎖)。batch 迴圈逐筆順序執行,維持整體單線。

## Risks

- **R1**: GPSS INFO token per-search 仍需每筆重抓 → session 復用的增益主要在 TLS 連線 + Cloudflare cookie,非省略握手。緩解:這正是抗 challenge 的關鍵點,符合目標。
- **R2**: batch 鎖內呼叫 `extract_representative_figure`,它內部又可能呼叫 `gpss_pdf` 源(fetch_patent_pdf 的 gpss_pdf 分支)→ `gpss_download_patent_pdf` 會嘗試取**同一把** `_GPSS_SCRAPE_LOCK` → **死鎖**。緩解見 DD-7。
- **R3**: 重構搬移大段 scrape 程式碼,易引入抄寫錯誤。緩解:逐字搬移 + 既有 9 測試回歸 + 新增 session 測試。

- **DD-7**(解 R2 死鎖): `asyncio.Lock` 不可重入。batch 內非 TW 走 `extract_representative_figure` → `fetch_patent_pdf`,其 `gpss_pdf` 分支會呼叫 `gpss_download_patent_pdf` 再取鎖 → 死鎖。解法:`fetch_representative_figure`/`fetch_pdf` 的**鎖只在最外層(batch 或單筆工具)取一次**;session 方法本身**不取鎖**。`extract_representative_figure` 在 batch 鎖內呼叫時,其下游 `gpss_download_patent_pdf` 需走「不取鎖」的內層 impl。→ 重構為:`_xxx_impl`(無鎖,純流程)+ `@mcp.tool` wrapper(取鎖)。batch 與 session 一律呼叫 `_impl`,wrapper 只供外部單筆呼叫。

## Critical Files

- `src/patent_mcp_server/patents.py` — 全部改動集中於此。
- `tests/test_br20260628_figures.py` — 回歸基準;新增測試另開 `tests/test_gpss_session_batch.py`。

## Code anchors

- patents.py:80-88 節流器
- patents.py:1730-1848 代表圖 impl
- patents.py:1851+ pdf impl
- patents.py:2161-2299 fetch_patent_pdf(gpss_pdf 分支在 2246)
- patents.py:2431-2509 batch
