# Tasks: remediation_drawing-scraping-cdn

## 1. GPSS 單線程節流 (A)

- [x] 1.1 在 `patents.py` module-level 新增 `_GPSS_SCRAPE_LOCK = asyncio.Lock()` 與延遲常數讀取（env `GPSS_SCRAPE_MIN_DELAY`/`GPSS_SCRAPE_MAX_DELAY`，預設 1.0/3.0）
- [x] 1.2 為 `gpss_download_representative_figure` 包裹 `async with _GPSS_SCRAPE_LOCK:` + 鎖內 HTTP 前 `await asyncio.sleep(random.uniform(min,max))`
- [x] 1.3 同樣套用 `gpss_download_patent_pdf` 與 `gpss_download_patent_xml`（共用同一把鎖）
- [x] 1.4 確認 `patentmcp_batch_download_figures` 經由上述工具呼叫，自然繼承序列化

## 2. extract_representative_figure 新工具 (D)

- [x] 2.1 新增 helper：`_pdf_page_count(pdf_path)` 用 `pdfinfo`；`_pdf_page_text(pdf_path, page)` 用 `pdftotext -f N -l N`
- [x] 2.2 新增 `_locate_figure_page(pdf_path)`：跳過第 1 頁，逐頁找 `FIG\.?\s*1` / `图\s*1` / `圖\s*1` / `第\s*1\s*圖`；fallback reference-numeral 密度；無則 None
- [x] 2.3 新增 `_render_page_png(pdf_path, page, dpi=200)` 用 `pdftoppm -r DPI -f N -l N -png`
- [x] 2.4 新增 `@mcp.tool() extract_representative_figure(publication_number)`：呼叫 fetch_patent_pdf 取得 PDF token → blob_path 解析 → 定位 → 渲染 → put_bytes 回 handle + page_number
- [x] 2.5 找不到頁回 `{success:false, error:"NO_FIGURE_PAGE"}`；無 PDF 回 `NO_PDF`（E2E 驗證: 3 頁 PDF→FIG.1 定位 page 2→PNG 8689 bytes）

## 3. CDN 403 + EPO 單頁降級 (B + F)

- [x] 3.1 `gpatents_download_figure` 捕捉 `httpx.HTTPStatusError`，403 → 回 `{success:false, error:"CDN_FORBIDDEN", downgrade_hint, url, http_code:403}`
- [x] 3.2 `fetch_patent_pdf` epo_images 分支：下載 PDF bytes 後以 `_pdf_bytes_page_count` (pdfinfo) 取頁數
- [x] 3.3 頁數 ≤ 1 → attempt 記 `EPO_BIBLIO_ONLY_1PAGE` + `pages`，`continue` 到下一來源（不落地、不 return）（驗證: 單頁 bytes count=1）

## 4. 縮圖解析度警語 (E)

- [x] 4.1 `gpatents/client.py` `_flatten`：thumb 存在時加 `representative_figure_resolution: "thumbnail"`（驗證: 有縮圖→thumbnail，無→None）
- [x] 4.2 companion skill（`pdf-figure-extraction.md` §3.2a/§3.2b）補 extract_representative_figure、代表圖優先級鏈與「縮圖禁用於報告」警告

## 5. 跨容器 token 對齊 (C, 已批准 → 採 host-pipe SOP)

- [x] 5.1 撰寫 `docker-mount-proposal.md`：現況 named volume 隔離問題、方案評估、影響面、回滾
- [x] 5.2 使用者批准「完整做完」；偵查後修正方案：A 撤回（違反 docxmcp bind-mount ban / AC-01）、B 需跨 repo 改 docxmcp（留給其 spec）、**採 C host-pipe SOP**（patentmcp 側單方面、零 policy 衝突）
- [x] 5.3 驗證 host-pipe 跨容器實際可行：patentmcp blob (TCP 8000, http=200, 50026 bytes, %PDF magic) → docxmcp `/files` tarball upload → 有效 token，bytes 完整，全程不經 model context
- [x] 5.4 固化 SOP 進 skill `pdf-figure-extraction.md` §3.4（跨容器 token 中轉 host-pipe）+ §3.2 步驟2 警告

## 6. 驗證與收尾

- [x] 6.1 新增單元測試：concurrency 序列化計時、403 降級結構、FIG.1 定位、單頁偵測（mock）— 9/9 PASS
- [x] 6.2 `import patent_mcp_server.patents` smoke test — 通過
- [x] 6.3 同步 `specs/architecture.md` Debug/Observability Map（抓圖邊界 + C 中轉）
- [x] 6.4 收尾 `event_record`（Key Decisions / Validation / Remaining）
