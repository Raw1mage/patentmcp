# BR_20260707 — 缺「分類軸批次匯出」能力：patent_search 用相關性檢索語義閹割了 GPSS expQty 大量匯出

- **狀態**：OPEN
- **嚴重度**：High（阻塞「專利全景」窮盡取數；導致 patentdb 累積半殘 row）
- **回報情境**：智慧家庭異常偵測 AIOT 全景擴充 — 需把某 IPC 分類軸的完整書目一次批次拉下轉 CSV，但現有工具做不到，只能逐條檢索、且塞進 patentdb 的是缺英文標題的半殘 row。

## 一句話

`patent_search` 是「**相關性檢索**」語義（keyword 疊 AND、`num` 預設 30、官方 miss 就退爬蟲），做不到「**純分類軸 + 大 expQty 批次匯出**」；而 GPSS 端點本身完全支援（`expQty` 可大、`expFld` 欄位齊）。缺一支「分類軸批次匯出」工具。

## 根因（已讀原始碼定位）

### 1. GPSS 端點本身支援大量批次匯出

`src/patent_mcp_server/gpss/client.py`：
- 單一端點 `GET .../gpss_api?userCode=...`（line 23）
- `expQty`（一次回幾筆）由 `num` 控制，`_build_query` 直接寫進 query（line 89）—— **GPSS 對 expQty 無小上限**，這是 TIPO「一次匯出大量」的原生能力
- `expFld` 預設 `PN,ID,TI,IN,PA,AB,CS,CL`（line 31）—— **欄位齊全含標題(TI)/申請人(PA)/摘要(AB)/CPC(CS)/claims(CL)**
- `expFmt` 只有 `json`/`xml`（line 88）—— **無 csv 格式**；CSV 是 TIPO 網頁介面功能，API 層要自己從 JSON 轉

### 2. patent_search 的檢索語義擋在前面

實測 `patent_search(ipc="G16H40/67", keyword="独居 老人 监测", databases=["CN"], num=50)`：
```
gpss: miss (zero_hits)  →  epo: parse error  →  ppubs: skipped  →  error_code: SCRAPING_REQUIRED
```
- keyword 被當 **AND 收窄**疊在 IPC 上 → 過度收窄 → 官方 0 命中 → 退爬蟲
- `num` 預設 30（`patent_search` 簽名），非為「把整個分類軸拉下」設計
- **本質是「找最相關的幾件」，不是「把某軸全部匯出」**

### 3. 後果：patentdb 累積半殘 row

- 走 `import_records()` inline 旁路吸收（`patentdb_store.py` line 450），塞進去的是 **search 當下的殘缺回應**
- EPO biblio 路徑（二段式）不回英文標題 → 今日 306 件 `title_en` 空白
- `put()` 是 COALESCE-only（line 238，非空不覆寫）→ **未破壞既有資料、無真垃圾**，但半殘 row 需事後逐件回官方補齊
- 對照組：GPSS 路徑（`expFld` 含 TI）抓的件標題齊全 → 證明半殘來自 EPO biblio 而非 GPSS

## 要求（工具層修，不徒手繞道）

新增一支「**分類軸批次匯出**」工具（或給 `patent_search` 一個 `mode="bulk_export"` 旗標），語義為：

1. **純分類軸**（`ipc`/`cpc`/`uspc`），**不強制疊 keyword AND**（keyword 若給只作 OR 加權，不作收窄）
2. **大 `expQty`**（例如允許 `num` 到數千～上萬，對齊 TIPO 每日配額），分頁 `expSkip` 自動翻頁拉完整軸
3. **強制 `expFld=PN,ID,TI,IN,PA,AB,CS,CL`**（欄位齊全，杜絕半殘）
4. **官方 miss 不退爬蟲**（批次匯出是官方 GPSS 能力，miss 就是真 0，不該 fallback 爬蟲）
5. 落地為完整書目 `records`（或直接 CSV），供 `import_csv` 吸收 → patentdb 只進完整 row

## 附帶：patentdb 半殘 row 補齊

- 今日 306 件 `title_en` 空白件，因 `put()` COALESCE-only，逐件 `patent_search(pub_number=)` 回 GPSS 重取即自動補齊英文標題（不破壞既有欄位）
- 或等本工具修好後，用「分類軸批次匯出」重抓對應軸，`import_csv` 覆蓋補齊

## 驗證方式

修好後：`<新工具>(ipc="G16H40/67", databases=["CN"], num=2000)` 應一次回數百～數千件**含標題**的完整書目，`title_en`/`title_orig` 非空率接近 100%，且不觸發 SCRAPING_REQUIRED。

## 環境

- `GPSS_USER_CODE` 需已設（容器/cfg 層，當前 host env 不可見）
- 相關檔案：`gpss/client.py`（expQty/expFld）、`patents.py`（patent_search 簽名 line 339 起）、`patentdb_store.py`（import_records line 450 / put COALESCE line 238）
