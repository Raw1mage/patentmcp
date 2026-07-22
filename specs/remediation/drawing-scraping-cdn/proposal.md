# Proposal: remediation_drawing-scraping-cdn

## Why

執行專利前案檢索與 Word 分析報告產出時，代表圖（representative figure）取得流程遭遇多重結構性失敗，導致報告中嵌入錯誤或低品質圖片。來源：`issues/BR_20260628_drawing_concurrency_scraping_remediation.md`（Open/High）。六個磨擦點橫跨抓圖併發控制、CDN 防盜鏈、跨容器隔離、PDF 代表圖頁面選擇、縮圖解析度與 EPO 單頁降級。

## Original Requirement Wording (Baseline)

- BR_20260628 六項磨擦點 A~F + 嚴格天條（零臨時腳本繞道、爬蟲單線程保護、縮圖禁用於報告、EPO 單頁識別降級）。
- 使用者裁示（2026-06-28）：「建 plan，六項一次做」。

## Requirement Revision History

- 2026-06-28: initial draft created via plan-init.ts
- 2026-06-28: 依 BR_20260628 與使用者裁示填入六項 A~F 範圍。

## Effective Requirement Description

1. **A — GPSS 抓圖單線程節流**：對 `tipo.gov.tw` 的自製爬蟲請求（`gpss_download_representative_figure` / `gpss_download_patent_pdf` / `gpss_download_patent_xml`）強制 process 級序列化（Concurrency=1），請求間插入隨機延遲（1~3s），防 Cloudflare Managed Challenge 觸發超時。
2. **B — Google CDN 403 偵測降級**：`gpatents_download_figure` 對 `patentimages.storage.googleapis.com` 回傳 403 時，必須明確識別為防盜鏈阻斷並回傳結構化降級訊號，引導改走 PDF 分解流程，而非靜默失敗或盲目重試。
3. **C — 跨容器 token volume 對齊**：撰寫 docker mount 對齊方案草案（host 工作區絕對路徑掛載到 patentmcp 與 docxmcp 相同內部路徑），使 PDF 落地檔可跨容器以絕對路徑中轉。**實際施作需使用者批准（needsApproval）**。
4. **D — extract_representative_figure 高階工具**：新增工具接受 `publication_number`，自動執行 PDF 下載 → 定位首個 `FIG. 1`/`图1`/`圖1` 頁（跳過封面與純文字頁）→ 200+ DPI 渲染 → PNG handle。取代「選最大檔案」策略（掃描版 PDF 會選到文字密集頁）。
5. **E — 縮圖解析度警語**：`gpatents_search` / `_flatten` 結果為 `representative_figure_url` 標註解析度等級（thumbnail），並在 companion skill 明確警告「索引縮圖不可用於報告嵌入」。
6. **F — EPO 單頁偵測降級**：`fetch_patent_pdf` 經 `epo_images` 取得 PDF 後，若頁數 ≤ 1，標記為「僅含著錄摘要，無附圖」並降級（不將著錄摘要頁誤作代表圖），對 CN/TW 案優先改走 GPSS / 其他全文來源。

## Scope

### IN
- `src/patent_mcp_server/patents.py`：GPSS 抓圖工具加 concurrency lock + 隨機延遲（A）；新增 `extract_representative_figure`（D）；`fetch_patent_pdf` 加 EPO 單頁偵測（F）；`gpatents_download_figure` 加 403 降級訊號（B）。
- `src/patent_mcp_server/gpatents/client.py`：`_flatten` 標註 `representative_figure_url` 解析度等級（E）。
- `skills/patentworks/`：companion skill 強化代表圖取得優先級鏈與縮圖禁用警告（B/D/E）。
- docker mount 對齊**草案文件**（C，待批准）。
- 單元測試 + import smoke test。

### OUT
- 不私自撰寫臨時爬蟲 / HTTP 下載腳本繞道工具缺陷（天條）。
- C 的 docker mount 實際施作（僅出草案，等批准後另行）。
- CNIPA 官方全文整合（F 提到的長期方向，本次僅做 EPO 單頁偵測 + 既有 GPSS 降級）。

## Non-Goals

- 不改 GPSS / Google / EPO 的檢索（search）路徑語意，只動抓圖與 PDF 取得。
- 不引入新的 fallback「自動續跑」機制掩蓋失敗（天條 11）；降級必須是顯式、可觀測、可被呼叫端決策。

## Constraints

- **爬蟲天條**：自製爬蟲必須 Concurrency=1，禁平行多線程。
- **縮圖禁用**：`representative_figure_url`（60x80）嚴禁用於交付報告。
- **EPO 單頁降級**：PDF 頁數 ≤ 1 須識別為著錄摘要並降級。
- **零臨時腳本**：工具缺陷一律回 patentmcp 更新，不臨時繞道。
- Async 架構：抓圖工具為 `async def`，concurrency lock 用 `asyncio.Lock`（module-level，跨工具共用一把鎖以序列化所有 tipo.gov.tw 請求）。

## What Changes

- GPSS 抓圖三工具改為共用一把 module-level `asyncio.Lock`，並在鎖內請求前 `asyncio.sleep(random.uniform(1,3))`。
- 新增 `extract_representative_figure` MCP 工具（PyMuPDF 渲染）。
- `fetch_patent_pdf` 在 epo_images 成功後檢查頁數，≤1 視為失敗轉下一來源並記 attempt 原因。
- `gpatents_download_figure` 捕捉 403 回 `{success: False, error: "CDN_FORBIDDEN", downgrade: "use_pdf_pipeline"}`。
- `_flatten` 為縮圖 URL 加 `representative_figure_resolution: "thumbnail"` 註記。
- skill 文件補代表圖優先級鏈與警告。

## Capabilities

### New Capabilities
- `extract_representative_figure(publication_number)`: PDF → FIG.1 頁定位 → 高 DPI PNG handle。

### Modified Capabilities
- `gpss_download_representative_figure` / `gpss_download_patent_pdf` / `gpss_download_patent_xml`: 共用單線程鎖 + 隨機延遲。
- `gpatents_download_figure`: 403 顯式降級訊號。
- `fetch_patent_pdf`: EPO 單頁著錄摘要偵測與降級。
- `gpatents_search` 結果: 縮圖解析度等級標註。

## Impact

- 受影響程式：`patents.py`、`gpatents/client.py`。
- 受影響 skill：`skills/patentworks/SKILL.md` 及相關 flow。
- 受影響文件：`specs/architecture.md`（Debug/Observability Map 抓圖邊界）。
- 依賴：PyMuPDF（fitz）需確認已在 `pyproject.toml`。
- Operator：C 的 docker mount 變更需重啟容器（待批准）。
