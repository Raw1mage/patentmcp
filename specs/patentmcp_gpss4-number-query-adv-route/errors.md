# Errors: patentmcp_gpss4-number-query-adv-route

## Error Catalogue

| Code | Condition | Surface | Recovery |
| ---- | --------- | ------- | -------- |
| `GPSS4LoginBusyError` | login gate 已被別的登入模式 tool 持有 | raise（帶現持有者 tool 名 + 取得時間） | 呼叫端等現有登入工作結束再重派；不排隊不自動重試（§4A 天條） |
| `GPSS4DbScopeError` | `_ensure_query_ready` 設定 DB scope 失敗（設定頁缺 checkbox / save 未確認 / 未知 DB code） | raise（DD-6 fail-fast） | 查詢中止；不用可能錯的現有 scope 續查；檢查設定頁結構 / 登入狀態 |
| `GPSS4AdvZeroHits` | adv 查詢真 zero-hit（DB_OK 但全部 0 筆） | 結構化空池回傳（非錯誤） | 判定 not_found（真無，非假 miss） |
| `GPSS4AdvSearchError` | adv 查詢流程失敗（無結果頁 / dual-view 切換失敗） | raise | 檢查 query 語法 / session 有效性 / TIPO 頁面結構 |
| `not_found`（status） | 號碼查詢 0 hit | resolve 記錄 status=not_found | 該號真未公開或申請號錯；非系統缺陷 |
| `unmatched`（status） | 命中 hit 但 parse 不出 pub_no | resolve 記錄 status=unmatched | 本 BR 修復前的主症狀；改 adv 路徑後應大幅下降；殘留者記證據待查 |
