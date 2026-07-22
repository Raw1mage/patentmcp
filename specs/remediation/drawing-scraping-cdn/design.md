# Design: remediation_drawing-scraping-cdn

## Context

BR_20260628 六項代表圖取得失敗，根因橫跨三層：(1) 自製爬蟲併發未鎖 → Cloudflare challenge；(2) CDN/EPO 來源對新案或非歐美案的內容限制；(3) PDF 代表圖頁面選擇策略錯誤。本設計在 patentmcp 工具層與 companion skill 固化修復，遵守爬蟲天條與零臨時腳本規範。

## Goals / Non-Goals

### Goals
- GPSS 抓圖請求全程序列化（Concurrency=1）且有隨機節流。
- 提供可靠的 PDF→代表圖頁→高清 PNG 原生工具，取代「選最大檔案」。
- CDN 403 與 EPO 單頁著錄摘要均顯式偵測並降級（不靜默、不誤用）。
- 縮圖 URL 明確標註等級，skill 警告禁止用於報告。

### Non-Goals
- 不整合 CNIPA 官方全文（長期方向）。
- 不改檢索（search）語意。
- 不新增任何自動續跑型 fallback（天條 11）。

## Decisions

- **DD-1**: GPSS 抓圖併發鎖採 **module-level 單一 `asyncio.Lock`**（`_GPSS_SCRAPE_LOCK`），由三個 GPSS 抓圖工具（figure/pdf/xml）共用。理由：Cloudflare 是針對來源站 `tipo.gov.tw` 的，需序列化「所有」對該站的爬蟲請求，而非各工具各自一把鎖。同一 event loop 內 `asyncio.Lock` 足以序列化；patentmcp 為單進程 async server，無需跨進程鎖。

- **DD-2**: 隨機延遲在鎖內、實際 HTTP 動作前 `await asyncio.sleep(random.uniform(GPSS_MIN_DELAY, GPSS_MAX_DELAY))`，預設 1.0~3.0s，可由環境變數 `GPSS_SCRAPE_MIN_DELAY` / `GPSS_SCRAPE_MAX_DELAY` 覆寫。理由：BR 天條明示「每次請求間隔強制隨機等待 1~3 秒」。延遲放在鎖內確保序列化節流；放鎖外會讓並發請求同時 sleep 後齊發。

- **DD-3**: `extract_representative_figure` 的 PDF 渲染採 **poppler CLI（`pdftoppm` + `pdfinfo` + `pdftotext`）subprocess**，不引入 PyMuPDF/fitz。理由：(1) 環境已有 poppler 24.02 與 Pillow，PyMuPDF/pypdf 皆缺；(2) 避免新增 AGPL 風險的重二進位依賴（PyMuPDF 為 AGPL，本產品 MIT）；(3) poppler 為工具原生 subprocess 呼叫，非「臨時繞道腳本」——它是固化進 MCP 工具的實作。`pdftotext -layout` 逐頁抽文字定位 `FIG. 1`，`pdftoppm -r 200 -f N -l N -png` 渲染該頁。

- **DD-4**: 代表圖頁定位演算法：逐頁 `pdftotext` 抽文字，跳過第 1 頁（封面/著錄），尋找首個符合 `FIG\.?\s*1\b` / `图\s*1` / `圖\s*1` / `第\s*1\s*圖` 的頁。找不到時 fallback 到「圖說密度最高頁」（reference-numeral 數量），仍找不到則回 `{success: False, error: "NO_FIGURE_PAGE"}` 不亂猜。理由：避免重蹈「選最大檔案」選到文字頁的覆轍；明確 fail 而非靜默選錯。

- **DD-5**: CDN 403 降級為**顯式結構化訊號**，非自動續跑。`gpatents_download_figure` 捕捉 `httpx.HTTPStatusError` 403 → 回 `{success: False, error: "CDN_FORBIDDEN", downgrade_hint: "use extract_representative_figure (PDF pipeline)", url: ...}`。理由：天條 11 禁止靜默 fallback；降級提示交由呼叫端（skill/AI）決策，不在工具內自動轉抓。

- **DD-6**: EPO 單頁偵測在 `fetch_patent_pdf` 的 `epo_images` 分支，下載 PDF bytes 後用 `pdfinfo`（讀 stdin）取頁數；若 `pages <= 1` → 記 attempt `{ok: False, error: "EPO_BIBLIO_ONLY_1PAGE"}` 並 `continue` 到下一來源（gpss_pdf / google_citation），不將著錄摘要 PDF 落地當代表圖來源。理由：BR_F 明示 EPO 對 CN/TW 只回著錄摘要；頁數≤1 是可靠判據。

- **DD-7**: 縮圖等級標註在 `gpatents/client.py` 的 `_flatten`，新增欄位 `representative_figure_resolution: "thumbnail"`（當 thumb 存在）。理由：在資料源頭標註，所有 `gpatents_search` 結果一致帶等級；skill 端據此警告。

- **DD-8**: docker mount 對齊（C）僅產**草案文件** `plans/.../docker-mount-proposal.md`，不改 `docker-compose.yml` / `.mcp.json`。理由：跨容器 infra 變更需重啟兩個容器、影響 docxmcp，屬 `needsApproval` 的 architecture_change，依使用者選項「C 會先提你批准」。

## Risks / Trade-offs

- **R1**: poppler `pdftotext` 對掃描版（純影像）PDF 抽不到文字 → FIG.1 定位失效。緩解：fallback 機制（DD-4）+ 明確回 NO_FIGURE_PAGE，由呼叫端決定是否人工指定頁。掃描版本就無 OCR 文字層，這是資料限制非工具缺陷。
- **R2**: `asyncio.Lock` 只在單 event loop 有效；若未來改多 worker 進程，需升級為檔案鎖。當前單進程架構下無此風險，記入 observability。
- **R3**: 隨機延遲增加批量抓圖總時長（N 件 × 平均 2s）。可接受——天條優先於速度。

## Critical Files

- `src/patent_mcp_server/patents.py`：GPSS 抓圖三工具（A）、`extract_representative_figure` 新增（D）、`fetch_patent_pdf` EPO 單頁（F）、`gpatents_download_figure` 403（B）。
- `src/patent_mcp_server/gpatents/client.py`：`_flatten` 縮圖等級（E）。
- `skills/patentworks/SKILL.md` + flow：代表圖優先級鏈與警告（B/D/E）。
- `tests/`：新增 concurrency / pdfinfo / figure-page 單元測試。

## Code Anchors

- `patents.py:1491` `gpss_download_representative_figure`（A 改造點）
- `patents.py:1601` `gpss_download_patent_pdf`（A 改造點）
- `patents.py:1474` `gpatents_download_figure`（B 改造點）
- `patents.py:1933` `fetch_patent_pdf` epo_images 分支（F 改造點）
- `gpatents/client.py:128` `_flatten`（E 改造點）
