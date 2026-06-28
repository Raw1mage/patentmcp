# Tasks: gpss-session-reuse-batch

## 1. 重構 GPSS scrape 為「無鎖內層 + 取鎖外層」分離

- [x] 1.1 將 `_gpss_download_representative_figure_impl` 內「自建 client」改為接收注入的 `httpx.AsyncClient` 參數(無鎖、純流程);保留現有 scrape 步驟逐字不變
- [x] 1.2 將 `gpss_download_patent_pdf` 的 scrape 流程抽成 `_gpss_download_patent_pdf_impl(pn, client)`(無鎖、純流程)
- [x] 1.3 驗證:既有 9 個 BR_20260628 測試仍全綠(import smoke + unittest)

## 2. 新增 `_GpssScrapeSession` 共用 session 物件

- [x] 2.1 新增 `_GpssScrapeSession` class:`__init__` 建單一 `httpx.AsyncClient`(headers/follow_redirects/timeout 對齊現況);`fetch_representative_figure(pn)` / `fetch_pdf(pn)` 各呼叫對應 `_impl(pn, self._client)`;`async close()`
- [x] 2.2 確認 cookie jar 由單一 client 全程持有(httpx.AsyncClient 預設帶 cookies),逐筆復用

## 3. 重構單筆 GPSS 工具為使用 session helper

- [x] 3.1 `gpss_download_representative_figure` wrapper:取 `_GPSS_SCRAPE_LOCK` → pace → 建 size=1 session → fetch → close;對外回傳結構不變
- [x] 3.2 `gpss_download_patent_pdf` wrapper:同 3.1 模式
- [x] 3.3 驗證單筆工具回傳結構與重構前一致(mock client 測試)

## 4. 重構 batch 工具:全批共用 session + 修非 TW 分支 bug

- [x] 4.1 `patentmcp_batch_download_figures`:取鎖一次 → 建一個 `_GpssScrapeSession` → for pub 逐筆(i>0 先 pace);TW 走 `session.fetch_representative_figure`,非 TW 走 `extract_representative_figure(pub)`
- [x] 4.2 移除 bug 路徑:不再呼叫 `get_patent()` 取 `representative_figure_url`;保留 cooldown/skip 邏輯
- [x] 4.3 `finally: await session.close()` 確保 session 關閉
- [x] 4.4 解 R2 死鎖:確認 batch 鎖內呼叫 `extract_representative_figure`→`fetch_patent_pdf`→gpss_pdf 分支時,下游走**無鎖** `_impl`,不再重取 `_GPSS_SCRAPE_LOCK`

## 5. 測試與驗證

- [x] 5.1 新增 `tests/test_gpss_session_batch.py`:mock 驗證 batch 全程只建一個 client(session 復用);非 TW 走 extract_representative_figure(非縮圖);TW 走 GPSS;某筆失敗不中斷
- [x] 5.2 跑全測試套件(舊 9 + 新),全綠
- [x] 5.3 import smoke test:`python -c "import patent_mcp_server.patents"`

## 6. 收尾

- [x] 6.1 更新 `specs/architecture.md`(若動到模組邊界)或註記 Verified (No doc changes)
- [x] 6.2 event_record 收尾紀錄(Key Decisions / Validation / Remaining)
- [x] 6.3 提示使用者 plan ready for verified

## 7. (extend) 抽統一 `SoftScrapePolicy` + 補齊全爬蟲面節流

- [x] 7.1 新增 `SoftScrapePolicy`(`patents.py` 或 `util/soft_scrape.py`):per-host 物件,持 `asyncio.Lock` + min/max delay + cooldown park。提供 `guard()`(async-cm:取鎖→等過 cooldown→pace→yield)、`park_cooldown(s)`、`note_block(text)`。taxonomy 明確:只序列化+pace+park,不丟棄請求
- [x] 7.2 GPSS 既有 `_GPSS_SCRAPE_LOCK`+`_gpss_scrape_pace` 收斂進一個 `_GPSS_POLICY = SoftScrapePolicy(...)`,三個 wrapper(figure/pdf/xml)統一用 `async with _GPSS_POLICY.guard()`
- [x] 7.3 修既有不一致 bug:`gpss_download_patent_pdf` / `_xml` wrapper 補上遺漏的 pace(原本只有 figure wrapper 有)

## 8. (extend) GPSS xml 跟上 session 復用 + ppubs 節流

- [x] 8.1 `_gpss_download_patent_xml_impl` 改吃 `session_client`(對齊 figure/pdf);`_GpssScrapeSession` 加 `fetch_xml(pn)`
- [x] 8.2 為 USPTO ppubs 加主動節流:`PpubsClient` 內加 `SoftScrapePolicy`,`make_request` 走 `guard()`(序列化+pace),429 時 `park_cooldown`
- [x] 8.3 `ppubs_batch_get_claims` 固定 0.5s sleep 改走 policy pace(統一機制)

## 9. (extend) 測試與收尾

- [x] 9.1 新增 `SoftScrapePolicy` 單元測試(序列化、pace 範圍、cooldown park、guard 不丟請求)
- [x] 9.2 GPSS xml session 復用測試;ppubs 節流序列化測試
- [x] 9.3 全測試回歸(舊 15 + 新),import smoke
- [x] 9.4 architecture sync + event_record 收尾
