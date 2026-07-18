# FR: patent_bulk 應支援 fields 精簡回傳（bulk 全撈的 caller context 成本歸零）

- 日期：2026-07-10
- 類型：feature request
- 元件：`patent_bulk`（search_dispatcher.py bulk()）
- 提出脈絡：AIOT 非接觸異常偵測 v3 精雕迴圈 D4 逐頁全撈（subagent ses_0b4e1f1f1 實測）

## 問題

`patent_bulk` 的用途是**全撈落地 patentdb**（per-page absorb），caller 根本不需要
biblio 內文——但每頁 20 筆完整 record（title/abstract/ipc...）仍經 MCP 回到 caller
context。大 total（1000+ 筆 = 50+ 頁）的逐頁驅動迴圈，caller context 被無用內文
灌爆：一個 subagent 只能跑 ~30 頁就得交棒，一條 2370 筆的檢索式要 3-4 個 subagent
接力，交棒座標協調成本高。

實測：container 無 CLI 旁路（`patent_mcp_server` 無 module CLI；MCP gateway
`/patentmcp/mcp` 404），無法從 bash 驅動迴圈跳過內文——MCP 回傳是唯一通道。

## 建議

`patent_bulk` 加參數 `fields`（或 `return_records: bool`，預設 true 向後相容）：
- `fields=["pubno"]` 或 `return_records=false` 時只回：
  `{success, total, next_skip, exhausted, patentdb_absorb: {imported, updated, skipped}, pubnos: [...]}`
- pubnos 保留（membership/provenance 需要），內文不回——absorb 已落地，內文可事後
  從 patentdb 查

## 效益

- 50 頁迴圈的 caller context 成本從 ~50×20 筆內文降到 ~50 行統計
- 單一 subagent 可跑完任意大 total，不需接力交棒

## 驗收

- `patent_bulk(..., return_records=false)` 回傳無 records 內文、有 pubnos + absorb 統計
- 預設行為不變（向後相容）

---
## 結案（2026-07-19）

以 `return_records: bool = True`（預設向後相容）落地於 `patent_bulk` MCP wrapper 層（`src/patent_mcp_server/patents.py` `_bulk_slim()`），dispatcher 層 untouched（DD-7 精神）：
- `return_records=false` 時：absorb 照常全量落地 patentdb → 回傳把 `records[]` 換成 `pubnos[]`（membership/provenance 保留）+ `records_returned: false` 標記；`total`/`next_skip`/`exhausted`/`patentdb_absorb`/`sharding` 等驅動欄位全數保留。
- 只裁剪 success envelope；error envelope 原樣通過（不遮 debug 證據）。
- 驗證：`_bulk_slim` 3 case 單元測試（slim/back-compat/error passthrough）+ 既有 store/slice 測試 20 passed。

**Scope 註**：GPSS 側大池（萬行級）正解仍是 `gpss4_advanced_search` 的 token/file delivery rail；本修法解的是 `patent_bulk` 逐頁驅動迴圈（EPO 或中等 GPSS slice）的 caller context 灌爆問題。
