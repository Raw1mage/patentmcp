# Errors: patentmcp_gpss-web-login-db-scope

## Error Catalogue

| Code | Condition | Surface | Recovery |
| ---- | --------- | ------- | -------- |
| `GPSS4_LOGIN_FAILED` | GPSS4 member 登入失敗（既有 `GPSS4LoginError`） | tool 回 `{success:false, error_code}` | 檢查 `GPSS4_USERNAME/PASSWORD`；不靜默降級匿名/REST |
| `GPSS4_DBSCOPE_SETTING_PAGE_NOT_FOUND` | 找不到 `_20_*` 設定頁 anchor（member.html 無或改版） | tool 回 error_code + dump 線索 | 重新逆工設定頁 anchor；停下回報 |
| `GPSS4_DBSCOPE_FAILED` | 勾庫存檔 POST 未成功跳回（庫範圍未生效） | tool 回 error_code | fail-fast，不用舊範圍續查（使用者天條） |
| `GPSS4_DBSCOPE_UNKNOWN_DB` | `databases` 含設定頁無對應 checkbox 的庫代碼 | tool 回 error_code + 合法庫清單 | 修正 databases 參數 |
