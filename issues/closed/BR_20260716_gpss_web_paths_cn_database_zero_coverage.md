# BR: ~~gpss_web_search / gpss4_advanced_search 兩條 web 路徑對大陸（CN）庫回 0~~【WITHDRAWN — 非 tool bug】

- **日期**: 2026-07-16
- **狀態**: **Withdrawn (2026-07-16 self-corrected)** —— 原定性錯誤，經使用者糾正 + 實證確認**非 tool bug**。真因是呼叫端把 gpss3 REST 的日期語法 `ID=2024-01-01:...` 套用到 gpss4 進階檢索（gpss4 只認 `AD=2024:2024` 申請年區間）→ total=0，與庫覆蓋無關。gpss3 匿名不含 CN 是**預期設計**。詳下 RCA。
- **嚴重度**: ~~high~~ → **N/A（撤回）**
- **來源**: 異常偵測前案檢索案（TIPO 得獎級）B2aC1 CN 軸實撈，REST 額度耗盡後改試 web fallback
- **相關（同族但正交，不受本次撤回影響，維持原狀）**:
  - `issue_20260716_gpss_web_patdb_country_narrowing.md`（observing）—— patDB **限縮**未生效
  - `issue_20260716_gpss_web_search_totals_missing_main_count_line.md`（open）—— totals 漏解析「共 N 筆」主計數行
- **實作位置**: `patents.py:_gpss_web_search_impl`；`gpss4_advanced_search` impl（`gpss4/adv_search.py`）

---

## ⚠ 撤回聲明（WITHDRAWN）

本 BR 原以為發現「web 路徑對 CN 庫回 0」的第三個獨立缺陷。經使用者糾正 + 實證復現，**此定性錯誤，非 tool bug**。以下保留原錯誤論證供追溯，並附真因 RCA。

## 原錯誤定性（WITHDRAWN，保留追溯）

原 BR 主張：`gpss_web_search`(gpss3) 與 `gpss4_advanced_search`(gpss4) 兩條 web 路徑對 CN 庫**均回 0**，根因為 **web 端登入路徑預設庫集不含大陸公開/公告全庫**（判為 tool bug，建議 dump web 資料庫選取表單、補齊庫勾選、三姊妹 issue 合併重構 web 庫範圍管理）。

原實測表（保留）：

| 路徑 | 大陸公開 | 大陸公告 | 全部命中 | records/patents |
|---|---|---|---|---|
| **REST `patent_bulk(source=gpss, databases=["CNA","CNB"])`** | — | — | **455 筆 CN**（combo1 同軸落地，ledger 有據） | 455 筆完整書目 |
| **`gpss_web_search`（gpss3 登入路徑）** | 0 | 0 | grand_total=2（僅 TW） | `records:[]` |
| **`gpss4_advanced_search`（gpss4 進階路徑）** | 0 | 0 | **total=0** | `patents:[]` |

## 真因 RCA（使用者糾正 + 實證）

原表兩條 web 路徑「回 0」各有不同、且**都不是 web 端庫覆蓋 bug**：

1. **`gpss_web_search`（gpss3）不含 CN = 正常設計，非 bug**。gpss3 走**匿名**登入路徑，其預設檢索庫集本就不含大陸公開/公告全庫。要查 CN 本就該走 gpss4 **登入**路線（使用者原話：「你用 gpss3 匿名登入當然預設資料庫不含大陸。你要走 gpss4 登入路線去搜尋」）。

2. **`gpss4_advanced_search`（gpss4）回 total=0 的真因 = 日期語法套錯**，與庫覆蓋無關：
   - gpss4 走 `GPSS4_USERNAME` / `GPSS4_PASSWORD` **登入**路線，庫集含**跨國全庫（含 CN）**。
   - 原 BR 的 gpss4 query 帶了 `ID=2024-01-01:2024-12-31`——這是 **gpss3 REST 的日期語法**。
   - gpss4 進階檢索的合法欄位碼只有 **`@TI` / `@AB` / `@CL` / `CS=`（分類）/ `AD=`（日期，申請年區間如 `AD=2006:2007`）**，明確 `NOT TI=(詞)` 亦不認 `ID=`——見 `src/patent_mcp_server/gpss4/adv_search.py` line 41-43 的官方 field-code 表註解。
   - 語法不合 → 引擎回 total=0（等同無效查詢），**不是 CN 庫沒資料**。

### 實證（改用正確 `AD=` 語法後 gpss4 立即命中，且確實含 CN）

```
# gpss4 正確語法（AD= 申請年區間）→ 命中
gpss4_advanced_search(
  query="(激光雷达 or 摄像 or 图像)@TI,AB and (老人 or 跌倒 or 生命体征)@TI,AB and AD=2024:2024",
  max_pages=1, delivery="none")
→ total=1, hit_count=1（命中 TW113127766 熱成像跌倒檢測案）

# 放寬 query → total=9，含 CN 語彙摘要案 + TW/JP/WO 多國
→ 證明 gpss4 登入庫集為跨國全庫、確實含 CN
```

## 結論與處置

- **WITHDRAWN — 非 tool bug**。`gpss4_advanced_search` 功能正常；`gpss_web_search`(gpss3) 匿名不含 CN 是預期設計。原「web 路徑庫覆蓋 bug」定性作廢，原「dump 庫選取表單 / 補齊庫勾選 / 三姊妹 issue 合併重構」建議一併作廢。
- **呼叫端教訓（真正的 fix，落在使用方）**：呼叫 `gpss4_advanced_search` 時，日期**必須**用 `AD=<年>:<年>` 申請年區間語法，**不可**套用 REST 端的 `ID=` 或 `date_from`/`date_to`。查 CN 走 gpss4 登入路線，不走 gpss3 匿名。

### 殘留的**真**限制（非 bug、是 API 特性，記錄供未來參考，不另發 BR）

- gpss4 進階檢索語法層**無國別/庫別限定碼**（無 `PD=` / `databases` 等效欄位），無法只鎖 CNA/CNB，撈回的是跨國混合池；`PD=CN` 為**非法語法**會回 0（此為語法不合，非 CN 無資料）。
- 若需分國同源池，須在**離線層按 pubno 國別前綴分流**（CN… 前綴入 CN 池，其餘另存），而非期望檢索層限國。這是既定 workaround，非工具缺陷。
