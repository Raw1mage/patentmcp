# BUG REPORT (工具): fetch_patent_pdf provenance 誤導、抓圖工具參數命名不一、extract_representative_figure 掃描版失效、ppubs_get_full_document 兩段 guid 摩擦

**Date**: 2026-06-28
**Status**: Resolved (2026-06-28, plan `br20260628_tooling_skill_gpss_gaps`)
**Priority**: Medium

> **修復摘要**:A `fetch_patent_pdf` 加 `allow_scraping=False` 顯式 gate(官方來源 miss 回 `SCRAPING_REQUIRED`,不靜默走爬蟲);B 參數統一 `publication_number(s)` + 舊名 alias;C `extract_representative_figure` 失敗分級(掃描版回 `NO_FIGURE_PAGE_BUT_IMAGES_PRESENT` + image_count);D `ppubs_get_full_document` 加 `publication_number` 便利包裝(自動 pub→guid)。20 tests 全過。
**Target**: patentmcp 工具層（`fetch_patent_pdf` / `extract_representative_figure` / `patentmcp_batch_download_figures` / `ppubs_*` / `patent_get_claim1`）
**Reporter**: AI Agent (代表 User)
**Source Session**: iSafe2.0 報告 R2 後續取圖/取文實測

---

## 1. 磨擦點與問題描述 (Friction Points)

### A. `fetch_patent_pdf` 描述寫「Routes official sources first」，實際對三件案全部 fallback 到 GPSS 爬蟲，且唯一的爬蟲訊號藏在 provenance

* **現象**：工具描述是「Fetch a patent's original PDF... Routes official sources first」，讀起來像「優先官方、安全」。但三件案（US20230081319A1 / CN120672280A / CN120543023A）實測回傳全部是：
  ```
  source: "gpss_pdf"
  provenance: { "api": "TIPO GPSS headless session", "scraping": true }
  ```
  也就是「官方優先」那一步都 miss，直接落到 GPSS headless 爬蟲。**唯一能判斷「這其實是爬蟲」的訊號，是埋在 `provenance.scraping` 的布林值**——工具名與描述都沒有任何爬蟲提示。
* **後果**：AI（包括我）會把 `fetch_patent_pdf` 當成無需同意的官方工具直接呼叫，**在不知情下觸發爬蟲**。本 session 我就這樣對三件案各跑了一次 GPSS headless 抓取，事後才從 provenance 發現。若 §5 同意天條要認真執行，這個工具的「官方外觀」會讓 AI 系統性繞過同意門檻。
* **RCA**：工具把「官方來源」和「GPSS 爬蟲 fallback」融進同一個呼叫，但沒在**呼叫前**讓 AI 知道會走哪條路；爬蟲與否變成**事後**才能從 provenance 得知的隱性事實。

### B. 取圖/取文工具的參數命名不一致 — `patent_number` vs `publication_number` 反覆試錯

* **現象**：同一批工具，參數名互相打架：
  | 工具 | 正確參數 | 我先試錯的參數 |
  |---|---|---|
  | `extract_representative_figure` | `publication_number` | `patent_number`（被拒）|
  | `patent_get_claim1` | `publication_number` | `patent_number`（被拒）|
  | `ppubs_batch_get_claims` | `patent_numbers`（複數陣列）| — |
  | `fetch_patent_pdf` | `publication_number` | — |
* **後果**：每個工具都要先撞一次 validation error 才知道正確參數名。`patent_number` / `publication_number` / `patent_numbers` 三種命名在同一工具家族並存。
* **RCA**：工具家族沒有統一的參數命名規約。

### C. `extract_representative_figure` 對掃描版 PDF 直接 `NO_FIGURE_PAGE`，但圖明明在 PDF 裡

* **現象**：`extract_representative_figure(US20230081319A1)` 回 `{success:false, error:"NO_FIGURE_PAGE", detail:"No FIG.1 marker and no usable text layer (likely a scanned PDF without OCR)"}`。但同一份 PDF（`fetch_patent_pdf` 已抓回的 1.44MB / 20 頁）實際含 **20 個 image XObject**——圖就在裡面，只是該工具靠「FIG.1 文字標記」定位，掃描版無文字層就放棄。
* **後果**：工具回「沒有代表圖」是**偽陰性**——不是沒有圖，是定位策略對掃描版失效。AI 讀到 `NO_FIGURE_PAGE` 會誤判「此案無圖可取」。
* **RCA**：`extract_representative_figure`（BR_20260628 D 的修復版）改善了「選最大檔」的舊問題，但新策略「找 FIG.1 文字標記」對**無文字層的掃描版 PDF** 仍然失效，且失敗時沒有退而求其次（如：回傳「PDF 有 N 個內嵌影像，無法判定哪張是代表圖，請人工挑選」而非一律 `NO_FIGURE_PAGE`）。
* **建議修復**：失敗分級——(1) 有文字層→找 FIG.1；(2) 無文字層但有 image XObject→回傳影像清單 + 頁碼供挑選（OCR 或啟發式：跳過封面、挑第一張線條圖比例的影像）；(3) 真的無影像→才 `NO_FIGURE_PAGE`。

### D. `ppubs_get_full_document` 需要 guid + source_type 兩段，無法直接吃 publication number

* **現象**：`ppubs_get_full_document(query="US20230081319A1")` 回 `{error:"guid and source_type parameters are required"}`。要先 `ppubs_search_patents` 取 guid 再取全文。但 `ppubs_search_patents(query="US20230081319A1")` 對 publication number 直接查 → `numFound:0`（PPUBS 的 q 語法不吃裸 pub number）。
* **後果**：US 案全文（含附圖）這條官方路徑，因為兩段式 guid + 查詢語法門檻，實測走不通；最後是 `ppubs_batch_get_claims`（單獨工具）才成功補到 claim 1。
* **RCA**：PPUBS 的 guid-based API 與「給 pub number 取全文」之間缺一層自動橋接。
* **建議修復**：提供 `ppubs_get_full_document(publication_number=...)` 的便利包裝，內部自動完成 pub number → 正確 PPUBS 查詢語法 → guid → full document，讓 AI 不需手動串兩段。

---

## 2. 影響範圍 (Blast Radius)

* A 最關鍵：任何呼叫 `fetch_patent_pdf` 的 AI 都可能在不知情下觸發爬蟲，使 §5 同意天條形同虛設。
* B 拖慢每次取圖/取文（每工具撞一次參數錯誤）。
* C 製造「此案無圖」的偽陰性，直接導致報告代表圖無謂缺失。
* D 讓 US 案官方全文/附圖路徑實測走不通。

## 3. 建議修復總表 (Proposed Remediation)

1. **A**：`fetch_patent_pdf` 在**呼叫前**就該能宣告路由意圖——或拆成 `fetch_patent_pdf_official`（純官方、失敗就失敗）與 `fetch_patent_pdf_gpss`（明確標爬蟲、需同意旗標）；或加 `allow_scraping:bool` 參數（預設 false，false 時官方 miss 就回「需爬蟲，請授權」而非靜默 fallback）。
2. **B**：統一參數命名為 `publication_number`（單）/ `publication_numbers`（複），其餘設為 alias。
3. **C**：`extract_representative_figure` 失敗分級 + 掃描版回影像清單供挑選，不要一律 `NO_FIGURE_PAGE`。
4. **D**：`ppubs_get_full_document` 加 `publication_number` 便利包裝，內部自動橋接 guid。

## 4. 驗證手段 (Validation Plan)

* A：修復後，`fetch_patent_pdf`（預設不允許爬蟲）對三件案應回「官方來源無此 PDF，需授權 GPSS 抓取」，而非靜默回 `scraping:true` 的 PDF。
* C：`extract_representative_figure(US20230081319A1)` 應回「PDF 含 20 個影像、建議第 N 頁」而非 `NO_FIGURE_PAGE`。
* D：`ppubs_get_full_document(publication_number="US20230081319A1")` 一次取得全文。
