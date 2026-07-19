# BR: gpss4_resolve_appnos 對公開號誤入 + hits>0 卻 result-list 不 render（追加）

- **狀態**: closed (resolved, 2026-07-20)
- **修復**: spec `patentmcp_gpss4-number-query-adv-route` amend DD-8/DD-9。缺陷A: `pubno_convert.tw_number_kind` SSOT 純函式 + `gpss4_resolve_appnos` 入口 fail-fast 分流（已公開/公告識別號→`already_identifier` passthrough，不投 adv、不計 consecutive error）。缺陷B: 新增 `GPSS4AdvRenderPending`，hits>0-no-render 降級為 recoverable `render_pending` 不中斷整批（取代誤導的 `retry the query` 硬 error）。驗證 40 pass/0 fail。缺陷B 完整 in-batch 解號 deferred（tasks 7.6 [~]，live 無法必現 hits>0-no-render 窗口；缺陷A 分流後公開號不再誤入 @AN 軸，生產故障已根除）。
- **回報者**: 前案檢索案（異常偵測 non-contact priorart）消費端
- **回報日**: 2026-07-19 晚
- **關聯**: BR_20260719_gpss4_folder_search_missing_dbscope_and_output_field_activation（已 closed，resolved）；其 §5 綠燈為真但**未覆蓋本 BR 兩個生產場景**
- **不阻本案定稿**：本案這 99 件已於 DD-104 坐實為號碼錯位假缺口（97 件本是公開號早已 enriched 有 abstract、2 件已解證書號），resolve_appnos 修否與本案封版無關。此 BR 純為 patentmcp 硬化，交 patentmcp 排期。

## 症狀（消費端實測，非推測）

前 BR closed 後，親自重跑先前爆掉的場景 `gpss4_resolve_appnos(pending_tw_99.txt)`，**與修前一樣停在 `CONSECUTIVE_ERRORS`**：

```
processed=10  resolved=2  error=8  via_adv=2  effective_scope=[TWA,TWB]
```

resolved 的 2 件是早期申請號（`TW087209080→TW509151U`、`TW080203372→TW245891U`，尾 U=新型證書號，正確）。error 的 8 件**全是 `TW20xx` 格式**（`TW200644333`/`TW201021598`/…/`TW202242807`）。

## 修前 vs 修後 error 對比（證明 BR 有動 code，但沒真修好此場景）

| | 修 BR 前 | 修 BR 後（本次實測） |
|---|---|---|
| error 訊息 | `adv form not reachable (no _3_10_X; len=289); wrong tab URL or session not authed?` | `search completed with 2 hits but the result list did not render (search-ready shell; per-DB counts={'全部': 2, '本國公開': 0, '本國公告': 2}) — retry the query` |

**這個變化本身是 root cause 鐵證**：
- 修前：連 adv 表單都到不了（像沒登入 / scope 沒設）
- 修後：**scope 設對了、搜尋成功、命中 2 筆、per-DB counts 有數字**（`本國公告=2`）——但**結果清單沒 render**。這與號碼格式、登入都無關，是 **result-page render-state** 問題（疑與既有 event `event_2026-07-16_gpss4-pat-no-null`／§65「結果頁需 select_hit/scope 才 render pat_no」同根）。

## 兩個獨立缺陷

### 缺陷 A：公開號誤入 appno 軸應 fail-fast 分流，而非丟進 adv 查到爆

那 8 件 `TW20xx` 本來就是**對外公開號（識別號最終形態）**，根本不該進 `resolve_appnos`（appno→pubno 專用軸）。目前行為是照丟進 adv 查 → hits=2 → render 失敗 → 累計 CONSECUTIVE_ERRORS 中斷整批。

**需求**：`resolve_appnos` 入口對每筆做**號碼形態判別**——`TW\d{9}` 且西元年前綴（`TW20xx`/`TW19xx`）= 已是公開號，應 fail-fast 標 `already_identifier`（或直接 passthrough 回傳該號），**不投入 adv 查詢**、**不計入 consecutive error**。避免「乾淨輸入被污染輸入拖垮整批」。

### 缺陷 B：hits>0 但 result-list 不 render 時，`retry the query` 未真 retry / 未換 render 觸發

per-DB counts 已證明查詢命中（`本國公告=2`），但結果列表 DOM 沒 render 出可抽號的 row。error 文字寫 `retry the query` 但實際沒重試、或重試用同一條不會 render 的路徑。

**需求**：hits>0 而 list 未 render 時，應觸發既有的 render 修復路徑（select_hit / 切表格式檢視 / scope re-render，見 §65 與 pat_no render 系列 event），而非直接記 error。這是把「搜到了卻抽不到號」從 error 降為可回收。

## 驗證建議（patentmcp 修後 §5 應覆蓋，避免再漏）

1. **混合輸入 batch**：`resolve_appnos` 餵一份**含公開號 + 民國年申請號混合**的清單（如 pending_tw_99.txt），斷言：公開號 → `already_identifier` passthrough（不進 adv）；申請號 → 正常 resolve；**不因公開號誤入而中斷整批**。
2. **known-item render**：對 `TW200644333`（per-DB counts 已證命中）斷言最終抽得到公開公告號（非 render error）。
3. 前 BR §5 的乾淨 6 筆仍應綠。

## 附：完整 error 樣本

```
TW200644333 :: GPSS4AdvSearchError: search completed with 2 hits but the result list did not render (search-ready shell; per-DB counts={'全部': 2, '本國公開': 0, '本國公告': 2}) — retry the query
```
（TW201021598 / TW201607443 / TW201614603 / TW202223848 / TW202224629 / TW202225914 / TW202242807 同形）
