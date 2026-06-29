# BR_20260629 — 代表圖管道對失敗案靜默 fallback 抓「錯件專利」並回報成功

> **STATUS: RESOLVED (2026-06-29)** — PDF 身分校驗層已落地於 `patents.py`
> (`_PDF_PUBNO_RE` / `_pubno_digit_core` / `_detect_pdf_pubno_cores` /
> `_verify_pdf_identity`)。`extract_representative_figure` 與 `fetch_patent_pdf`
> (gpss_pdf 來源) 落地前校驗 PDF 內文 publication number,不符回
> `WRONG_PATENT_FETCHED` 不落地、不回 success。回歸測試見
> `tests/test_br20260628_figures.py::PdfIdentityVerificationTest`(6 項全綠)。

## 現象（含硬證據）

iSafe2.0 報告 R3 補三件代表圖時，`CN120543023A` 落地的圖檔內容**不是該案**：

- 落地檔 `priorart_isafe20/04_report/media/fig_CN120543023A.png`（1654×2339）
  目視頁眉為 **「CN 121094816 A　説明書　4/11 頁」** —— 完全是另一件專利的 PDF 內頁。
  - md5: `0514ab73291b657a1a704ec319243b66`
- 使用者手動給的官方 GPSS 圖 URL
  `https://tiponet.tipo.gov.tw/gpss3/gpssbkmusr/00008/CNG2120543023A_000.jpg`（1000×956）
  目視為 CN120543023A 真代表圖（S1–S5 BIM 流程圖，與 Claim 1 S1–S5 完全吻合）。HTTP 200, 100163 bytes。
- 另兩件 `CN120672280A` / `US20230081319A1` 落地圖經目視**正確**（步驟一~四流程圖 / escrow 里程碑撥款流程圖），證明只有 CN543 走了錯誤路徑。

關聯 tool 軌跡（本 session）：CN543 在 `gpss_download_representative_figure` 後，又出現一筆
`fetch_patent_pdf(publication_number="CN120543023A", allow_scraping=true)`（622 chars 回應）——
代表 GPSS 圖對 CN543 取得失敗，流程 fallback 到 `fetch_patent_pdf`，而該 fallback 取回的 PDF
其實是 **CN121094816**（錯件），且整條鏈**回報 success**、沒有任何 publication_number 一致性校驗。

## RCA

1. **失敗被靜默 fallback 掩蓋**：`gpss_download_representative_figure` 對 CN543 的 G2 `_000` 取不到時，
   未 fail-fast，而是落入 PDF fallback 鏈（`extract_representative_figure → fetch_patent_pdf →
   gpss_pdf`，patents.py:155 附近）。
2. **fallback 來源回錯件且無身分校驗**：fetch_patent_pdf 對 CN543 取回的 PDF 封面/頁眉是
   CN121094816，但管道未把「下載到的 PDF 內 publication number」與「請求的 publication number」
   做一致性比對，於是錯件 PDF 被當成 CN543 的圖頁切出並落地。
3. **成功訊號與實際內容脫鉤**：工具回 `ok/success` 只代表「有抓到 bytes / 切出 PNG」，
   不代表「抓到的是請求的那件」。這正是「把單一工具輸出當資料源邊界、render ok≠內容正確」病根的
   一個實例——若非人工目視（render → 看頁眉），錯件圖會直接進入交付物。

## 建議修復

1. **GPSS 圖優先、fail-fast**：`gpss_download_representative_figure` 取不到 G2 序列時，
   應回傳明確 `figure_unavailable`（附嘗試過的 URL），**預設不靜默 fallback** 到 PDF 切圖管道；
   是否走 PDF fallback 應為呼叫端顯式選項（符合「禁止新增/依賴 silent fallback」天條）。
2. **fallback PDF 身分校驗（核心）**：任何經 `fetch_patent_pdf` / `extract_representative_figure`
   取回的 PDF，落地前必須校驗 PDF 內文/頁眉的 publication number 與請求號一致
   （normalize 後比對；CN 案頁眉格式 `CN <number> A`）。不一致 → 視為失敗，回
   `WRONG_PATENT_FETCHED`（附偵測到的號 vs 請求號），**不得落地、不得回 success**。
3. **回應夾帶 provenance**：圖/PDF 結果一律帶 `source`（gpss_g2 / pdf_fallback）、`source_url`、
   `detected_pubno`，讓呼叫端與人工 QA 能一眼看出來源與身分校驗結果。

## 影響範圍

- 任何「GPSS 圖失敗 → PDF fallback」的代表圖取得（跨國別），都可能落地錯件圖而回報成功。
- patentworks priorsearch 交付物（技術洞察報告）正確性：錯件圖會冒充前案代表圖，屬實質內容錯誤。
- 已知本次只有 CN543 觸發；其餘兩件正確。已用使用者驗證過的官方 GPSS 真圖人工更換並重建 docx。

## 驗證手段

- 修復後對 CN120543023A 重跑 `gpss_download_representative_figure`：應回真 G2 圖（S1–S5），
  或明確 `figure_unavailable`，**不得**再回 CN121094816 內頁。
- 注入式測試：請求號 A、令 GPSS 圖失敗、令 PDF fallback 取回號 B 的 PDF → 斷言管道回
  `WRONG_PATENT_FETCHED` 且不落地。

## 驗證責任歸屬（重要，定調 AI 工作流）

本次錯件圖是靠 AI render docx + 目視頁眉抓出的，但**那是補救手段、不是常態工作流**——
每張圖都 render+讀圖做視覺驗證對 token 成本極不友善。正解是把「圖身分正確性」推進工具層自動化：

- **工具層（自動，機器校驗）**：fallback PDF 落地前必做 `detected_pubno == requested_pubno`
  一致性比對（見上「fallback PDF 身分校驗」），不一致即 `WRONG_PATENT_FETCHED` 不落地。
  這是消除「錯件圖混入交付物」的根本手段，不依賴任何人或 AI 事後看圖。
- **AI（不再做）**：抓圖後**不再** render + 讀圖做視覺正確性驗證（太燒 token）。AI 只負責
  抓圖、落地、嵌入交付物；圖的「內容是否正確」交由**人工審閱**。
- **人審（最終把關）**：交付物中的圖正確性由人在審閱階段確認。

亦即：身分校驗自動化（工具層）+ 內容正確性人審，取代「AI 每張圖 render+讀圖」。
