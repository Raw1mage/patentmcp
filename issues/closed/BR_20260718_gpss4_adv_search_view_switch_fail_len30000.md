# BR_20260718: gpss4_advanced_search 特定 keyword 組合觸發 view switch 失敗(len≈30000, no rows)

- **狀態**: CLOSED(2026-07-18 修復;根因非 view switch,是 zero-hit 監測器壳誤判)

## 症狀
`gpss4_advanced_search` 在**特定 keyword 組合**下,內部「簡詳目並列」view switch 失敗,回傳 `len≈30000` 但無「公開公告號」rows,等於查無結果——但不是真的 zero_hits,是引擎視圖切換卡住。

## 重現
異常偵測前案檢索案 US 撈池,9 個 B×C 分片走 `gpss4_advanced_search @CPC`,**前 7 片同架構全正常回 pubno**,唯獨以下兩片穩定觸發:
- B2b×C-β:B2b 聲學壓感群(`"acoustic sensing" or ultrasonic or "pressure sensor" or piezoelectric ...`)AND C-β 居家場景群(`"home care" or "smart home" or indoor or bedroom or bathroom ...`)
- B2b×C-γ:同 B2b AND C-γ 照護對象群(`elderly or "older adult" or "nursing home" or caregiver ...`)

scope=USA/USB,`@CPC` 後綴,AD 年窗,delivery 純 JSON。

## 已窮盡的繞法(全無效)
1. 縮 CPC 碼群(27→少數碼)
2. 單碼
3. 縮 keyword 詞數
4. gpss3 路徑(不支援 databases scope,無法逐庫)

→ 判 patentmcp / gpss4 web 引擎側 bug,非查詢邏輯錯。

## 影響
US 全景池 B2b×{C-β,C-γ} 兩片 BLOCKED,誠實記入 run_ledger 缺口(`round=US-CPC-harvest`,兩片 total/landed=null)。B2b 聲學壓感是半接觸軸、C-α 才 4 筆,漏此兩片對 US 全景池影響邊際,但需 bug 修後補齊母體。

## 疑似根因方向(待 code 查證)
`len≈30000` 疑似回應體大小觸發某個 view 切換分支的 buffer/parse 邊界。這兩片的共通點:C-β/C-γ 場景詞(indoor/home/elderly...)在 US 庫是高頻泛用詞,AND B2b 後仍可能回大母體 → 觸發簡詳目切換時的 30000 邊界。建議查 `gpss4/adv_search.py` view switch(簡目↔詳目)的長度處理分支。

## Resolution(2026-07-18,活體復現坐實)

**真根因(與疑似方向不同)**:零命中檢索 GPSS4 server **永遠不渲染結果列表**——query POST 只回「檢索表單監測器壳」(`chkURL` 契約,len≈30k,「前次檢索還沒好」)。舊碼對這個壳硬做 view-switch POST → 誤報「簡詳目並列 view switch failed」。len≈30000 是該表單頁固定大小,非 buffer 邊界。

活體復現(2026-07-18,USA/USB scope + BR 同構 B2b×C-β query):監測器 `ttsserv_watch` 首輪即 `DB_OK` 且 per-DB 命中數 `全部(0)/美國公開(0)/美國公告(0)`——**兩失敗分片是真 zero-hit**(前 7 片成功因有命中才有結果列表),非引擎卡住。「B2b 聲學壓感 AND 居家場景 AND CPC 碼群 AND 2023 年窗」在 US 庫交集確實為空。

**修復**(`gpss4/adv_search.py`):
- 新辨壳契約 `_CHKURL_RE`(與結果頁 `AURL` job shell 區分)+ `_WATCH_COUNT_RE`(parse `全部(N)`)。
- `_submit_query` 無 result markers → `_search_ready_watch` 輪詢到 `DB_OK`:`全部(0)` → `GPSS4AdvZeroHits` → `harvest()` 回結構化空池 `{total:0, hit_count:0, zero_hits:true, db_counts, patents:[]}`(MCP 層 `success:true`);DB_OK 但 hits>0 無列表 → typed `GPSS4AdvSearchError` fail-loud。
- 驗證:失敗分片重跑回結構化 zero-hit JSON;`tests/test_br20260718_fixes.py` 固化壳/監測體 regex 契約(用活體擷取的真 HTML 片段)。

**對檢索案影響**:run_ledger 兩缺口片實為 `total=0`,可補記 landed=0,US 全景池無實質漏洞。

## 關聯
- 同案已記:`BR_20260717_gpss4_adv_search_uncaught_nameerror_dbscope.md`(NameError 路徑)
- `issue_20260716_gpss_web_search_totals_missing_main_count_line.md`(totals 缺 count 行)
- 本 BR 是 view switch 分支的第三個 gpss4 web 穩定性問題。

## 範圍擴大(2026-07-18 追測——非 B2b 專屬，TW 全軸 web 路徑全面失效)

> 初版認為這是 US 庫 B2b×{C-β,C-γ} 兩片的邊角問題。**實測推翻——TW 庫全軸首片就撞同一 bug，非 B2b 專屬。**

**TW 2023 年窗撈池實測(2026-07-18，6 發診斷探針)**：`gpss4_advanced_search` 對 **TW scope(TWA/TWB)** 全軸首片即撞 view switch 失效，`len` 恒定 **29648~30081**，與 query 寬窤/命中量完全無關：

| 探針 query | len |
|---|---|
| A軸27碼CS= and B1@TI and Cα@TI | 30081 |
| A軸縮5碼CS= and B1縮 and Cα縮 | 29785 |
| 純B×C無CS= | 29714 |
| CS=2碼 and B1縮 | 29680 |
| CS=單碼 expand_family=true | 29660 |
| 單碼單詞 跌倒 and 雷達 | 29648 |

**機制重新定性**：`len` 恒定 ~30000 且無 `公開公告號` rows ——這不是「結果太多撐爆」(單碼單詞也炋),是 gpss4 對 TW 庫的簡詳目並列 view **回一個固定約 30000 字元的錯誤頁**(無號 rows),parser 拓不到號。原推測「C-β/C-γ 高頻泛用詞→大母體→觸發 30000 邊界」**被推翻**：單碼單詞小母體也撞,非母體大小問題,是 **TW scope view 本身的系統性 bug**。

**繞法窮盡(TW,全無效)**：(1) 縮碼 27→5→2→單碼 全炋；(2) 拿掉 CS= 純 B×C 炋；(3) `expand_family=true`(另一 view)同炋；(4) `gpss_web_search`(gpss3) 回 `GPSS_WEB_DBSCOPE_UNSUPPORTED` 鎖不了 TWA/TWB。

**影響升級**：不再是 US 兩邊角片。**TW 全軸 web 撈池路徑全面失效**——配上 `BR_20260718_gpss_rest_bulk_parse_failed`(TW 中文 `patent_bulk` API 也 Cloudflare 截斷),**TW 兩條路(API + web)現在都不可用**。對本案：TW POC 新撈 2023 全軸池受阻,現有 34 筆舊池(DD-71 淺撈)是唯一 TW 新撈素材。

## 痑似根因方向補(TW——待 code 查證)
`len` 恒定 ~30000 強烈暗示：view switch 失敗時 gpss4 回的是一個**固定的錯誤/空結果頁模板**(約 30000 字元),非真結果頁。建議查 `gpss4/adv_search.py` 的簡詳目並列 view switch POST：TW scope(`_20_1_S_TA`/`_20_1_S_TB` field)下的 view switch form-data 是否與 US scope 不同(庫別特定的 hidden field / INFO / slot key 組裝),導致 TW 的 view switch POST 被伺服器拒絕→回錯誤頁。
