# Issue: gpss_web_search totals 漏解析「共 N 筆」主計數行，回殘留全庫母數誤導判讀

- **日期**: 2026-07-16
- **狀態**: open
- **來源**: 異常偵測前案檢索案沙盤 gpss_web_search，AI 誤把 totals 當命中數
- **相關**: `patents.py:_gpss_web_search_impl`（line 2909-3063）；姊妹 issue `issue_20260716_gpss_web_patdb_country_narrowing.md`

## 症狀

`gpss_web_search` 兩條不同布林式（`(radar)@TI` vs `("fall detection" and radar)@TI`，同 date window）
回傳的 `totals` / `grand_total` **完全相同（252,488）**，只有 `records` 內容不同。

- `provenance` 兩發都 `{"step":"poll","ok":true,"rounds":1}` —— poll 第一輪就 break。
- 消費端（AI）據此誤判「totals 是背景庫總數、與檢索式無關、不可信」。

## 根因（讀 code + 使用者判讀線索確認）

1. **totals 語義本身正確**：line 3018-3039 poll `ttsserv_watch`(t7) 拿 per-database 精確命中數，
   `grand_total = sum(totals.values())`（line 3049）。設計意圖是對的。
2. **但 poll 就緒判斷不足**：line 3028-3037 迴圈，db 還在計數時頁面顯示 countdown/reclock 才續 poll。
   rounds=1 就 break 代表**第一輪讀到頁面頂端「全部」欄位的殘留全庫母數**（各庫真命中數尚未刷新），
   卻已通過 break 條件回傳 → 消費端拿到的是全庫母數，不是檢索式命中數。
3. **漏解析真命中主行**：TIPO GPSS web 結果頁的**檢索式真命中數**在人類可讀主行
   「檢索結果： 共 359 筆，第 1/8 頁， 每頁 50 筆」（使用者提供的判讀線索）。
   現行 `_gpss_web_parse_totals` 只解析各庫分項 totals，**未解析這行「共 N 筆」主計數**。

## 影響

- 消費端無法用 `gpss_web_search` 的 totals/grand_total 作為檢索式召回母數（會拿到全庫殘留值）。
- 對照組 `gpss4_advanced_search` 正確回 `total`（= 頁面「共 N 筆」）+ `hit_count`，不受此缺陷影響
  —— 該案已改以 gpss4_advanced_search 為 web 路徑主撈引擎（見本案 DD-56）。

## 建議修法

1. **解析主計數行**：在 `_gpss_web_search_impl` 增解析「共 N 筆」regex（`共\s*([\d,]+)\s*筆`），
   回傳為新欄位 `result_count`（檢索式真命中數），與各庫分項 `totals` 分開。
2. **poll 就緒判斷加碼**：當「全部」欄位值等於前一輪殘留、且各庫分項全 0/缺，視為未就緒續 poll，
   避免第一輪殘留值就 break。
3. **文件標註**：tool docstring 明示 `totals`=各庫分項（需 poll 就緒）、`result_count`=檢索式命中母數
   （優先取此行），避免消費端誤用。

## workaround（現況）

需要檢索式真命中母數 + pubno 池時，改用 `gpss4_advanced_search`（回 `total`/`hit_count` + pubno 逐筆）；
`gpss_web_search` 目前僅適合快速存在性探針，其 totals 不可作召回母數。

---
## 結案（2026-07-19）

三項建議修法全部落地（`src/patent_mcp_server/patents.py`）：
1. **主計數行解析**：新增 `_gpss_web_parse_result_count()`（容忍「共」與「筆」之間的 markup 包裹，如 gpss4 的 numfmt font/span），回傳新欄位 `result_count`；`grand_total` 改為優先取 `result_count`。5 case 單元 sanity 通過（含千分位、markup 包裹、零命中、行缺失→None）。
2. **poll 就緒判斷加碼**：改為「連續兩輪 totals 完全相同」才 break（two-consecutive-identical-rounds stability check），杜絕 rounds=1 讀到殘留全庫母數即返回；provenance 補 `stable` 欄位。
3. **docstring 標註**：`gpss_web_search` 回傳說明明示 `result_count` = 檢索式權威命中數、`totals` = 各庫 advisory（僅 poll stable=true 時可信）。
