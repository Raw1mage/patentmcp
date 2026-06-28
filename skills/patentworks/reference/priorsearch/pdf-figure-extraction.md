# SOP: 取得專利全文/圖說/原始 PDF

> 目標:為 shortlist 的重點前案,取得(優先序)逐字 Claim 1 → 完整全文/圖說文字 → 原始 PDF/圖檔影像。落地於工作資料夾 `02_pool/shortlist.json` 與 `03_assets/patents/`(見 priorsearch.md §0)。

## 1. 能力盤點(實證,2026-06)

三層需求,三種現況:

| 需求 | 合法可靠途徑 | 狀態 |
|---|---|:---:|
| 逐字 Claim 1 / 全部請求項 | `google_get_patent_claims`(非TW)、`gpss_search(pub_number)`(三地)、`uspto ppubs`(US) | ✅ 可靠 |
| 完整說明書全文 + 附圖文字說明(BRIEF DESCRIPTION OF THE DRAWINGS) | `google_get_patent_description`(非TW)、`uspto ppubs_get_full_document`(US) | ✅ 可靠 |
| 原始 PDF / 圖檔影像 | `fetch_patent_pdf`(EPO images → Google citation fallback) | ✅ 可靠(見 §3) |

### 各來源的硬邊界(實測)
- **`fetch_patent_pdf`(統一工具,2026-06 上線)**:給**已知公告號**回原始 PDF 的 token handle。依序試 `epo_images`(EPO OPS 官方影像 API,零限速)→ `google_citation`(從專利頁解析真實雜湊 `citation_pdf_url` 再下載)。已端到端實證(TWI854998B → 63 頁 PDF → docxmcp decompose → ~45 張附圖 PNG)。
- **`google_*` BigQuery(`patents-public-data`)**:回 claims/description/書目**純文字**,實測 `google_get_patent` 完整輸出**不含任何 pdf/image/uri 欄位**——即 BigQuery **沒有圖檔影像或 PDF 連結**。涵蓋 US/EP/WO/JP/CN/KR/GB/DE/FR/CA/AU,**不含 TW**。
- **TIPO GPSS / OpenData**:GPSS 檢索 API 純文字;TIPO OpenData Open API(`cloud.tipo.gov.tw/S220/opdataapi/api/...?tk={token}`)只回**著錄資料**;TW 專利全文影像**僅以整批 TIFF 掃描資料集**(FTP/dataset 每月更新)開放,**無「給公告號→回該件影像」的單件 API**。→ TW 案原始檔改走 `fetch_patent_pdf` 的 `google_citation`(實證涵蓋 TW)。
- **USPTO PPUBS**:`ppubs_get_full_document` 取全文文字可靠;`ppubs_download_patent_pdf` 二進位下載實測 404(故 `fetch_patent_pdf` 不走此路)。

## 2. 文字優先(預設路徑,無需碰任何圖檔下載)

取**圖檔的文字說明**完全不需要原始圖檔。依法域:
- **非 TW 案**:`google_get_patent_description(publication_number="US-XXXXXXX-B2")` → 回完整說明書,含每個 FIG 的逐圖文字說明(如「FIG.5 預測跌倒用的狀態機狀態轉移圖(綠/黃/橘/紅四態)」)。逐字請求項用 `google_get_patent_claims`。
- **TW 案**:`gpss_search(pub_number="TW...", databases=["TWA","TWB"])`。
- **US 案(次選/交叉)**:`uspto_patents(method="ppubs_get_full_document", guid=...)`。

⚠️ **工具名辨識**:用 `google_get_patent_*`(BigQuery 合法 API),**不是** `gpatents_*`(網頁爬蟲,本 flow 禁用)。

## 3. 原始 PDF / 圖檔影像

### 3.1 紅線:爬蟲非法,禁用;但「針對已知專利逐件小量下載」合法
- **🚫 禁止**:`gpatents_search` / `gpatents_get` 等**批量爬取** patents.google.com 網頁。這是會被限速封鎖、且性質上屬爬蟲的行為。
- **✅ 允許**:針對 shortlist 上**已知的特定專利號**,**逐件、小量**下載 Google Patents 託管的**公開專利 PDF**。這是「對已知公開文件的單件存取」,不是批量爬取——量小(通常 ≤10 件)、目標明確(具體 PN)、檔案本身是公眾可免費取得的官方公報 PDF。

### 3.2 逐件 PDF 下載 → docxmcp 抽圖(統一工具 `fetch_patent_pdf`)
1. **下載**:對 shortlist 上**已知公告號**逐件呼叫 `fetch_patent_pdf(publication_number="TWI854998B")`。
   - 工具內部依序試 `epo_images`(EPO OPS 官方影像 API,零限速)→ `gpss_pdf`(TIPO 單線程)→ `google_citation`(從專利頁解析真實雜湊 `citation_pdf_url` 再下載)。**無需自己拼 URL**。
   - ⚠️ **EPO 單頁降級(BR_20260628 F)**:EPO OPS 對許多 CN/TW 案只回**單頁著錄摘要**(無說明書附圖)。`fetch_patent_pdf` 已會偵測 `pdfinfo` 頁數 ≤ 1,記 `attempts[]` 的 `EPO_BIBLIO_ONLY_1PAGE` 並**自動降級到下一來源**;不會把著錄摘要頁誤當代表圖。
   - 回傳 docxmcp 風格 handle `{token, rel, download_url, bytes, sha256, source, provenance}`;PDF bytes 落在 token store,不經 model context。
   - ⚠️ **不要猜 URL**:`patentimages.storage.googleapis.com/pdfs/<PN>.pdf` 是**錯誤路徑**(GCS 對不存在 object 回 403,非 cooldown);真實 URL 是帶內容雜湊的 `/xx/yy/zz/<hash>/<PN>.pdf`,只能從專利頁的 `citation_pdf_url` meta 取得——這正是 `fetch_patent_pdf` 的 `google_citation` 在做的事。
   - 若要落地本地工作資料夾,用 handle 的 `download_url` 取 bytes 存進 `03_assets/patents/<PN>.pdf`。
2. **抽圖**:把 handle 的 `token` 交給 docxmcp `decompose`。⚠️ **跨容器 token 隔離(BR_20260628 C)**:patentmcp 與 docxmcp 是**獨立容器、獨立 named volume**,patentmcp 的 token **在 docxmcp 容器內看不到**,直接 `docxmcp_document(token=<patentmcp_token>)` 會回 `token_not_found`。必須先把 bytes 經 **host-side 管道**搬進 docxmcp 的 token namespace(全程 bytes 不經 model context),見 §3.4。搬進後得到 **docxmcp 自己的 token**,再 `docxmcp_document(action="decompose", format="pdf", token=<docxmcp_token>, path="<PN>.pdf")` → 從產出的 `media/pdf_objects/` 取圖檔(實證一件 TW 案抽出 ~45 張 PNG)。
3. **挑代表圖**:對照 §2 取得的附圖文字說明(FIG 編號↔內容),挑技術代表圖,複製進 `04_report/media/`。

### 3.2a 一鍵代表圖(高階工具 `extract_representative_figure`,BR_20260628 D)
若只需要**單張代表圖**(不需全部附圖),用統一高階工具一次完成 PDF 下載 → FIG.1 頁定位 → 高清渲染:
- `extract_representative_figure(publication_number="TWI854998B", dpi=200)` → 回 `{token, rel, download_url, bytes, sha256, page_number, dpi, locate_method, source_pdf}`。
- 內部:呼叫 `fetch_patent_pdf` 取 PDF → `pdftotext` 逐頁定位首個 `FIG. 1`/`图1`/`圖1`(跳過封面頁)→ `pdftoppm -r 200` 渲染該頁為 PNG。
- **取代失效的「選最大檔案」策略**:掃描版 PDF 每頁都是整頁位圖,文字頁往往比附圖頁更大,選最大檔案會選到 OCR 文字說明頁。本工具改以 FIG.1 文字定位,避免此坑。
- **明確失敗,不亂猜**:找不到 FIG.1 頁且無文字層(純掃描版)→ 回 `{success:false, error:"NO_FIGURE_PAGE"}`;全來源無 PDF → `NO_PDF`。此時走 §4 降級(Claim 1 + 圖說文字),不要硬塞錯頁。

### 3.2b 代表圖取得優先級鏈(務必依序,BR_20260628 B/D/E)
1. **Priority 1**:`extract_representative_figure(PN)` — 高階一鍵(PDF pipeline,報告級高清)。**首選**。
2. **Priority 2**:`gpss_download_representative_figure(PN)` — TW 案 TIPO 官方圖(已強制單線程 + 隨機延遲;勿並發呼叫)。
3. **Priority 3**:`gpatents_download_figure(figure_url)` — 僅當 figure_url 非 403;新案常觸發 CDN 防盜鏈回 `CDN_FORBIDDEN`,此時降級回 Priority 1 的 PDF pipeline。
4. **🚫 禁止**:直接使用 `gpatents_search` 結果的 `representative_figure_url` 嵌入報告。該欄位是 **~60x80 像素低解析度索引縮圖**(`gpatents_search` 結果已標 `representative_figure_resolution: "thumbnail"`),放大至報告寬度會嚴重模糊/發綠塊。縮圖**僅供辨識**,不可作為交付圖檔。

### 3.3 端點健康度 smoke test(動手前先驗)
下載前先用一件已知案(如 `TWI854998B`)試一發:
- `fetch_patent_pdf(publication_number="TWI854998B", include_attempts=true)` 是否回 success + 非零 bytes;看 `attempts[]` 確認哪個 source 命中(`epo_images` 或 `google_citation`)。
- 通 → 逐件下載 shortlist;全 source 失敗(`ALL_SOURCES_FAILED`)→ 看 `attempts[]` 的 error(`THROTTLED`/`NOT_FOUND`/`EPO_NOT_CONFIGURED`),429/503 為暫時限流可稍後再試,其餘走 §4 降級(早退:連 3 件失敗即判定當前不通)。

### 3.4 跨容器 token 中轉:patentmcp → docxmcp(BR_20260628 C,host-pipe)
patentmcp 與 docxmcp 是**獨立容器、獨立 named volume**;patentmcp 的 token 在 docxmcp 容器內**不可見**,直接把 patentmcp token 餵給 `docxmcp_document` 會回 `token_not_found`。正解是經 **host-side 管道**把 bytes 搬進 docxmcp 的 token namespace,**全程 bytes 不經 model context**:

- **patentmcp 服務位址**:TCP `http://localhost:8000`(blob 端點 `GET /files/{token}/blob/{rel}`)或 UDS `.run/patentmcp.sock`。
- **docxmcp 攝取入口**(官方,設計來跨容器收檔):
  1. `docxmcp_stage_dir` —— inline files-map(小檔可直接);或
  2. HTTP tarball upload —— `POST /files`(UDS `docxmcp.sock`,大檔/二進位首選)。

**一鍵 host-pipe(實證可行,token 完整搬移)**:
```bash
TOK=<patentmcp_token>; REL=<patentmcp_rel>   # 來自 fetch_patent_pdf / extract_representative_figure handle
tmpd=$(mktemp -d); cp /dev/stdin "$tmpd/$REL" < <(curl -s "http://localhost:8000/files/$TOK/blob/$REL")
tar -C "$tmpd" -cf - . | curl -s --unix-socket /home/<user>/projects/docxmcp/.run/docxmcp.sock \
  -X POST -H 'Content-Type: application/x-tar' --data-binary @- http://docxmcp.local/files
# → 回 {"token":"<docxmcp_token>","files":[{"relpath":"./<REL>","bytes":...}],"doc_dir":...}
rm -rf "$tmpd"
```
拿回 **docxmcp 自己的 token**(`tok_...`)後,再 `docxmcp_document(action="decompose", format="pdf", token=<docxmcp_token>, path="<REL>")` 抽圖。

> **2026-06-28 實證**:patentmcp blob(TCP 8000,http=200,50026 bytes,`%PDF-1.4` magic)→ host-pipe → docxmcp `/files` tarball upload 回有效 token,bytes 50026 完整;全程不經 model context。
>
> **為何不改 compose 對齊 volume**:docxmcp `docker-compose.yml` 有明文 `# NO -v <host-path>:<data-dir> bind mounts. Verified by AC-01.`(DD-13 lint),host-path bind mount 會打爆其 AC。共用 external named volume(方案 B)技術可行但需單方面改 docxmcp 架構政策,應由 docxmcp 自身 spec 流程主導。故 patentmcp 側採此 host-pipe SOP,善用 docxmcp 既有官方攝取入口。

## 4. 降級(`fetch_patent_pdf` 全 source 失敗時)
若 `fetch_patent_pdf` 回 `ALL_SOURCES_FAILED`(EPO 未設定 + Google 暫時限流等),以「逐字 Claim 1 + 附圖文字說明」(§2)替代原始圖檔,品質足以支撐技術洞察報告。報告 §4/§6 誠實標註:「原始附圖**影像**因下載來源暫時不可用(`attempts[]`: <error>),以逐字 Claim 1 + 附圖文字說明替代。」429/503 為暫時限流,可稍後重試。

## 5. 實作狀態(2026-06, plan `patent-pdf-fetch`)
原始圖檔能力**已實作並端到端驗證**:
1. ✅ **`fetch_patent_pdf` 統一工具**:`epo_images`(EPO OPS 官方影像 API)→ `google_citation`(專利頁 `citation_pdf_url` 解析)兩段路由,回 token handle。
2. ✅ **EPO OPS images**:`EPOClient.images()` + `download_image_pdf()`,復用既有 OAuth + 403/429 退避,零限速,補歐/PCT 案。
3. ✅ **Google citation**:`GooglePatentsClient.resolve_pdf_url()` 從專利頁抽真實雜湊 URL,嚴格拒絕猜測的 `/pdfs/<PN>.pdf` 路徑;涵蓋 TW(實證 TWI854998B)。
4. ✅ **端到端**:download → docxmcp `decompose format=pdf` → `media/pdf_objects/*.png`(一件 TW 案抽出 ~45 張)。
5. ⚠️ **仍待補**:USPTO PPUBS PDF(`ppubs_download_patent_pdf` 對已知 guid 仍 404,未納入路由);TW 案若要官方來源,TIPO OpenData 僅整批 TIFF 資料集(無單件 API)。
