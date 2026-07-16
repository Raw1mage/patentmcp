# issue: gpss4_advanced_search 結果頁 pat_no 抽不到（藏在 clickselect ajax rec-id，非明文；TW/US/CN 皆然）

- **日期**: 2026-07-16
- **狀態**: fixed（2026-07-17 簡詳目並列修法 live 驗證通過；見文末修復記錄）
- **嚴重度**: high（**跨國別普遍失效**：TW/US/CN 軸 pat_no 皆 null → 撈回的記錄無公開號，下游取文/去重全阻）
- **範圍修正（2026-07-16 回歸實測）**: 初判為 CN 頁專屬，但 task 4.2 TW/US 回歸（`radar@TI`, total=18517）**同樣 pat_no=null**——證明是**當前 GPSS4 結果頁佈局的普遍 parser 缺陷**，非 CN 專屬。**先於 BR_20260716 改動即存在**（`databases=None` 未動庫範圍程式碼也 null），故非該 BR 引入的回歸。
- **元件**: `src/patent_mcp_server/gpss4/adv_search.py` `AdvResultPage._extract_rows` / `AdvPatent`

## 症狀

`gpss4_advanced_search(databases=["CNA","CNB"], query=<CN 軸>)` 撈回 `total=68 / hit_count=50`，title/abstract 正常，但**每筆 `pat_no=null`**。實測（BR_20260716 task 4）：

```
country_prefixes: {"??": 50}   # 全部無 CN 前綴號碼
sample_pat_no: [null, null, ...]
```

## Root Cause 最終定案（playwright 實地逆工 2026-07-16，推翻早期 ajax 假設）

使用者領域知識 + playwright 實地互動定案。**非 ajax rec-id 問題，而是「檢視模式 + 國別選擇」問題**：

完整互動鏈（playwright 實驗證）：
```
登入 → 進階檢索填 query 送出 → 結果頁(混合「全部」)
  → sidebar 點國別 slot(大陸公開 href尾^17 / 公告^18，帶 R_rec 命中數)
  → 該國別頁(預設「條列式」檢視，只有序號 checkbox，号碼欄空白)
  → 點「表格式」檢視 icon(class=button JS綁定，4種:條列式/表格式/純文字/簡詳目並列)
  → POST gpsskm?@@<n> → 号碼列表 render
```
- **sidebar 國別清單 = 帳號 `_20_1_S_*` 設定的鏡像**（鎖 CN 後 sidebar 只列大陸公開/公告——反證 BR_20260716 庫範圍修法生效）。
- **pat_no=null 根因 = 現行 httpx 流程停在「條列式簡目」頁**，号碼欄未 render（非 parser 抽不到，是頁面根本沒輸出号碼）。要 (a)選國別 (b)切表格式檢視 POST 才有号碼。
- **headless 表格式 POST 回 500**（缺前置 state/referer，待解）。

## （早期）Root Cause（ajax 假設，已被上方推翻）

CN 結果頁的公開號**不在 HTML 明文儲存格**——`_extract_rows` 靠 `_KINDED`（`^[A-Z]{2}\d{6,}[A-Z]\d?$`）/ `_PAT_NO_RE` 從明文 cell regex 抽號碼，但 CN 頁把號碼藏在 row 的 ajax 觸發器裡：

```
clickselect(this,74,54600,1)   # db=74(大陸庫) rec=54600 curt=1
```

`grep -oiE "[A-Z]{2}[0-9]{6,}"` 對 CN page_1/page_2 **零命中**——明文確實沒有號碼，藏在 `clickselect` ajax（`^S^<db>_<rec>_<curt>_1^`）。**回歸實測發現 TW/US 頁同樣如此**（radar@TI total=18517，pat_no_populated=0）——即現行 GPSS4 結果頁**整體**把號碼移出明文儲存格、改藏 ajax rec-id，`_KINDED`/`_PAT_NO_RE` 的明文 regex 全數落空。先前「TW/US 放明文」的推測被回歸推翻。這是 GPSS4 結果頁佈局變更的**普遍**影響，與庫範圍設定機制正交。

## 與 BR_20260716 的關係（正交，不重複）

- `BR_20260716_gpss4_adv_search_missing_peruser_database_scope_config`（庫範圍設定）的修法**已驗證生效**：`dbscope_verify.html` 證實帳號檢索庫精確鎖成 `_20_1_S_CA`+`_20_1_S_CB`，CN 池撈回 total=68。
- 本 issue 是 CN 池撈回後的**下游 parser 缺陷**，不在庫範圍 BR 的修法範圍——分開處理避免局部修補破壞 TW/US 既有明文抽號路徑。

## 建議修法方向（未實作）

CN row 從 `clickselect(this,<db>,<rec>,<curt>)` 抽 `db_rec` → 發詳目 ajax（`^S^<db>_<rec>_<curt>_1^`）取真實公開號；或改走詳目頁補號。須 live 逆工 CN 詳目 ajax 回應格式，且不得退化 TW/US 明文路徑（schema-adaptive）。


## 修復記錄（2026-07-17，fixed）

**方向**：使用者拍板「全套登入模式聰明運作」——純 httpx 重放完整互動鏈，不引入 playwright runtime 依賴（playwright 僅作逆工學習工具）。

**關鍵逆工修正**（playwright request 攔截 pw_06_captured.json）：
- 「表格式」檢視 POST 在 httpx/playwright 下皆回 500 —— 棄用。
- 「**簡詳目並列**」檢視 POST 才是正解：`POST <km form action @@N>` with
  `INFO + @_0_15_T=T_XX + _0_15_T= + GPSSTECH= + @_0_48_A=A_ + _0_48_A=0 + JPAGE= + _IMG_簡詳目並列.x/.y + 每筆 @R<hex>_db_rec_n=1 hidden 回帶`。
- **不需要選國別 sidebar**：帳號庫範圍已由 `_20_1_S_*` 鎖定（BR_20260716），「全部」頁即等於鎖定範圍的池；直接在查詢結果頁 POST 檢視切換即可（sidebar 國別 slot GET 在 httpx 下踩 RefleshHtml 迷宮，繞過）。
- 每頁筆數：簡詳目並列頁的 `每頁 <select>` 是 slot-URL option，GET 值=50 的 option → 50 筆/頁。
- 翻頁：POST `_IMG_次頁.x/.y`（同款 form-data 形狀，每頁重讀 INFO/@R/action —— slot key 單次有效）。
- GPSS4 raw HTML 屬性**不帶引號**（`name=INFO value=...`）——regex 必須容忍。

**實作**（`src/patent_mcp_server/gpss4/adv_search.py`）：
- `_view_form_data()`：檢視切換/翻頁 POST 契約組裝。
- `_enter_dual_view()`：切簡詳目並列（fail-fast：無公開公告號 rows 即 raise，絕不靜默收割無號碼的條列式頁）+ 每頁=50。
- `AdvResultPage._extract_dual_rows()`：label-driven 欄位抽取（公開公告號/申請號/申請日/專利名稱/摘要——按標籤 map，不按位置），`html` 含 `公開公告號` 標記時自動走此路徑。
- `_harvest_pages()`：dual-view 分頁走 `_IMG_次頁` POST；legacy JPAGE 路徑保留。
- `harvest()`：`_submit_query` 後插入 `_enter_dual_view`。

**Live 驗證（2026-07-17）**：
- CN 軸（radar@TI, AD=2023:2024, total=18517）：150/150 pat_no 全覆蓋（3 頁×50），apply_no/title/date 齊。
- TW 軸（databases=[TWA,TWB], persist=False）：100/100，total=155。
- US 軸（databases=[USA,USB], persist=False）：100/100，total=1625。
- 回歸：`pytest tests/test_gpss_query_slice.py tests/test_gpss_session_batch.py` → 17 passed。

**契約恢復**：`gpss4_advanced_search` 回傳的每筆 patent record 重新攜帶公開公告號（pat_no）——下游取文/去重鏈路恢復。
