# BUG REPORT: Patent Figure Download Congestion, CDN 403 Block, and Container Isolation Issues

**Date**: 2026-06-28
**Status**: Resolved (2026-06-28 核實) — A/B/D/E/F code-done(commit 證據見各項);C 為設計使然,Won't-fix-by-design(走既有 `stage_file` host-bridge)
**Priority**: High
**Reporter**: AI Agent (on behalf of User)

> **核實摘要(2026-06-28,以 HEAD code 為準逐項核對,非 BR 原標籤)**:六項磨擦點裡 **A/B/D/E/F 五項早已 code-done**,每處皆有 `BR_20260628 X` 程式碼標記為證(A=`_GPSS_POLICY.guard()` 單線程鎖接 6 處,commit `ca19bc8`;D=`_locate_figure_page` FIG.1 定位取代選最大檔;F=`_pdf_bytes_page_count` EPO 單頁偵測;B=`patents.py` `CDN_FORBIDDEN` 顯式降級;E=`gpatents/client.py` `representative_figure_resolution=thumbnail` 標記 + skill §5 警示)。只有 **C(跨容器 token)是設計使然**:patentmcp/docxmcp 本就獨立容器各自 named volume,既有解法是 `stage_file`(落地 host 絕對路徑)+ `/files/{token}/blob/{rel}` 跨容器中轉——SKILL.md:35 已記載「交付物一律經 `stage_file` / docxmcp token+blob handle 交付」。硬掛共用 volume 反破壞隔離、違 fleet 慣例,故 **Won't-fix-by-design**。

## 1. 磨擦點與問題描述 (Friction Points)

### A. TIPO GPSS 抓圖觸發 Cloudflare JS Challenge (ReadTimeout)
> **✅ Resolved（commit `ca19bc8`）** — `SoftScrapePolicy`(`util/soft_scrape.py`)實作 per-host serialize（Concurrency=1）+ random pacing + cooldown-park,收斂為 `_GPSS_POLICY`;三個 GPSS 抓取 wrapper（figure/pdf/xml,patents.py:1781/1902/2054）全部包在 `async with _GPSS_POLICY.guard()` 內,共 6 處 guard 接線。`_GpssScrapeSession` 持久化單一 httpx client 跨批次重用 cf_clearance cookie。BR 發出（commit `99d8497`,15:01）當下 patents.py 尚無任何 lock,此鎖是本 BR 的回應(16:55 落地)。
*   **現象**：呼叫 `gpss_download_representative_figure` 抓取台案代表圖時，出現嚴重的 `httpcore.ReadTimeout` 錯誤，抓圖批量超時失效。
*   **RCA**：臺灣智慧財產局網站（`tiponet.tipo.gov.tw`）前方掛載了 **Cloudflare WAF**。當多個抓圖請求平行發送，或未嚴格模擬瀏覽器 JS 指紋時，會觸發 Cloudflare Managed Challenge（人機驗證）。由於 HTTP 客戶端無法執行 JS 挑戰，連接被 Cloudflare 靜默掛起，導致超時。
*   **天條約束**：GPSS 抓圖功能是自製爬蟲（非合法 API）。**必須永遠只准單線程（單一 Concurrency）順序執行，並加入隨機延遲**，以防被 Cloudflare/防火牆抓取封鎖。

### B. Google CDN 403 Forbidden 阻斷
> **✅ Resolved（`patents.py:1491`）** — `gpatents_download_figure` 偵測 Google Storage（patentimages CDN）的 anti-hotlink 403,回**顯式降級訊號** `{error:"CDN_FORBIDDEN", downgrade_hint:"use extract_representative_figure (PDF pipeline)", http_code:403}`,絕不靜默 retry 或 auto-redirect（符合天條 #11 fail-fast）。CDN 防盜鏈本身是 Google 政策、非我方可解除;工具能做的「顯式標記 + 指向 PDF pipeline」已到位。
*   **現象**：批量下載 2025 年後半極新專利的 `representative_figure_url` 時，Google Storage 直接返回 `403 Forbidden`。
*   **RCA**：Google Storage 對於新近公開的專利圖檔啟用了安全防盜鏈機制，匿名爬蟲請求會直接被 CDN 阻斷。

### C. 跨容器 Token Volume 隔離
*   **現象**：`patentmcp` 產出的 PDF token，在呼叫 `docxmcp` 的 `decompose` 工具時，回傳 `token_not_found`。
*   **RCA**：`patentmcp` 與 `docxmcp` 分屬兩個獨立的 Docker 容器，掛載了不同的 named volumes，導致 token 無法跨容器互通。必須下載到 Host 機本機目錄，以絕對路徑中轉處理。

### D. PDF 代表圖提取選錯頁面 — 「選最大檔案」策略失效
> **✅ Resolved（`patents.py:1586` `_locate_figure_page`）** — 新增 `extract_representative_figure` 高階工具,定位策略改為:跳過封面頁 → 找首個 FIG.1 文字標記頁(`_FIG1_PATTERNS`)→ 無標記時退到 reference-numeral 密度最高頁 → 200 DPI 渲染 PNG。徹底取代失效的「選最大檔」啟發式。掃描版無文字層時回 `NO_FIGURE_PAGE_BUT_IMAGES_PRESENT`(見 BR_20260628_figure_pdf §C/C-2,容器 poppler 補裝後實測 image_count:20)。
*   **現象**：使用 `pdf_extract_objects` 分解 PDF 後，以「選擇檔案體積最大者」作為代表圖。結果對於掃描版專利，被選中的是 OCR 全頁文字說明掃描圖（247KB），而非真正的附圖（較小的向量線條圖）。導致最終報告中貼的是整頁英文說明書而非流程圖。
*   **RCA**：「選最大檔案」策略在掃描版 PDF 中完全失效。掃描版 PDF 的每一頁都是一張完整的位圖，因此文字頁的位圖檔案往往比附圖頁更大（因為文字密度高、墨色面積大）。
*   **建議修復**：在 `patentmcp` 中新增 `extract_representative_figure(patent_number)` 高階工具。該工具應：
    1. 定位 PDF 中首次出現 `"FIG. 1"` / `"Fig. 1"` / `"图1"` / `"圖1"` 的頁面（跳過封面頁）
    2. 對該頁以 200+ DPI 進行高品質渲染
    3. 返回 PNG 圖片路徑

### E. Google Patents Storage 縮圖 URL 解析度極低
> **✅ Resolved（`gpatents/client.py:151`）** — `gpatents_search` 結果新增 `representative_figure_resolution` 欄位,thumbnail 時標 `"thumbnail"`,並在 code 註解 `BR_20260628 E: LOW-RES INDEX THUMBNAIL ~60x80 px, NOT report-grade`。skill §5(line 56)亦警示「`representative_figure_url` 代表圖縮圖...只在 ①②③④ 都填不了才用」。報告級附圖一律走 `extract_representative_figure`(PDF pipeline)。
*   **現象**：從 `representative_figure_url` 欄位取得的 Google Storage URL 包含 `60x80/` 路徑段，下載後實際寬度僅 60-80 像素。放大至 Word 6 吋寬度後極度模糊，且發綠色塊。
*   **RCA**：Google Patents 的 `representative_figure_url` 儲存的是**低解析度索引縮圖**，非原始說明書附圖。即便移除 `60x80/` 路徑段嘗試取得原圖，也會因防盜鏈返回 403。
*   **建議修復**：在 `gpatents_search` 結果中標註 `representative_figure_url` 的解析度等級（thumbnail vs full），並在 companion skill 中明確警告：「此 URL 僅為索引縮圖，不可用於報告嵌入。如需高清附圖，請使用 PDF 分解流程。」

### F. EPO OPS 下載的 CN/TW 專利 PDF 僅含 1 頁（著錄摘要頁）
> **✅ Resolved（`patents.py:2273` + `_pdf_bytes_page_count`）** — `fetch_patent_pdf` 的 EPO 分支偵測下載 PDF 頁數,`BR_20260628 F: EPO OPS only serves biblio (cover) pages for many CN/TW cases` → 頁數 ≤ 1 時不當成完整全文/代表圖,讓 fallback 鏈往下走(TW→GPSS 單線程、US→PPUBS)。EPO 對 CN/TW 只給著錄頁是 EPO OPS 服務範圍限制、非我方可解;工具能做的「偵測單頁 + 降級不誤用」已到位。
*   **現象**：透過 `epo_biblio` / EPO OPS 下載 CN 案與 TW 案 PDF 時，下載回來的 PDF 僅包含 1 頁（書目資料摘要），**不包含說明書附圖**。導致 PyMuPDF 只能渲染該唯一頁面（文字摘要），作為「代表圖」插入報告時顯示為文字頁而非流程圖。
*   **RCA**：EPO OPS 對非歐洲/美國專利的全文服務有限。對於 CN 和 TW 專利，EPO 僅提供著錄事項（bibliographic data）和摘要頁，**不提供完整說明書和附圖**。
*   **建議修復**：
    1. 在 `patentmcp` 的 Fallback 策略中增加判斷：若 EPO 下載的 PDF 頁數 ≤ 1，標記為「僅含著錄摘要，無附圖」
    2. 對 CN 案：改用 CNIPA 官方全文下載（如 `https://pss-system.cponline.cnipa.gov.cn/`）
    3. 對 TW 案：改用 TIPO GPSS 單線程下載或 TIPO 電子公報 PDF

---

## 2. 嚴格天條與規範 (Strict User Guardrails)

1.  **零臨時腳本繞道 (No Ad-hoc Scraping Scripts)**：
    *   嚴禁 AI 代理為了繞過工具缺陷而私下撰寫臨時爬蟲或 HTTP 下載腳本（例如 `download_google_figures.py`）。
    *   有任何工具開發或下載需求，**一律發送 Bug Report (BR) 給 `patentmcp`**，由工具主體更新。
2.  **爬蟲單線程保護 (Single-Threaded Scraping)**：
    *   自製爬蟲功能（如 GPSS 圖片抓取）必須強制進行單線程鎖定 (Concurrency=1)，絕對禁止平行多線程呼叫。
3.  **Google Patents 縮圖禁止用於報告嵌入**：
    *   `representative_figure_url` 欄位的圖片僅為低解析度索引縮圖（60x80 像素），**嚴禁直接用於任何交付報告**。如需高清附圖，必須走 PDF 分解流程。
4.  **EPO 單頁 PDF 識別與降級**：
    *   當 EPO 下載的 PDF 頁數 ≤ 1 時，必須識別為「僅含著錄摘要」並降級處理（以文字 Claim 對照代替），不得將著錄摘要頁誤作「代表圖」插入報告。

---

## 3. 治根建議方案 (Proposed Technical Fixes)

1.  **在 `patentmcp` 工具層實施 Concurrency Lock**：
    *   在 `gpss_download_representative_figure` 與 `gpss_pdf` 的代碼入口，加入進程級的鎖（Lock）或佇列（Queue），強制所有對 `tipo.gov.tw` 的請求進行序列化單線程執行，並在每次請求間隔強制隨機等待 1~3 秒。
2.  **改進 PDF 合法分解流程 (Fallback Strategy)**：
    *   在官方 GPSS/Google 圖片接口 403/超時失效時，將 **「透過 EPO OPS 官方影像 API / USPTO 下載說明書 PDF，再經由本地 pdf_objects 分解代表圖」** 固化為官方 API 的標準 Fallback 流。
3.  **在 `mcp.json` 中對齊 Host 絕對路徑掛載**：
    *   為了解決跨容器 token 隔離問題，修改 Docker 掛載配置，將 Host 的工作區目錄（如 `GoogleDrive/@Working/`）對齊掛載到兩台容器的相同內部路徑上，使得絕對路徑 directly 可用。
4.  **新增 `extract_representative_figure` 高階工具**：
    *   接受 `patent_number` 參數，自動執行完整的 PDF 下載 → 附圖頁定位（FIG. 1 文字搜尋）→ 高清渲染 → PNG 輸出流程。將目前散落在 Agent scratch 腳本中的邏輯固化為 patentmcp 原生工具。
5.  **在 companion skill 中強化代表圖取得的優先級鏈**：
    *   Priority 1: `gpss_download_representative_figure`（單線程）
    *   Priority 2: `gpatents_download_figure`（若非 403）
    *   Priority 3: `extract_representative_figure`（PDF 分解）
    *   **禁止**：直接使用 `representative_figure_url` 縮圖

