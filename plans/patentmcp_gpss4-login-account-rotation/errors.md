# Errors: patentmcp_gpss4-login-account-rotation

## Error Catalogue

| Code | Condition | Surface | Recovery |
| ---- | --------- | ------- | -------- |
| `GPSS4LoginError: login failed after trying N account(s)` | 帳號池所有帳號登入皆失敗（DD-5） | raise `GPSS4LoginError`，訊息含各帳號最後錯誤 | 檢查帳密正確性 / CAPTCHA md5 table / 網路；或於 `.env` 增設可用帳號 |
| `GPSS4LoginError: GPSS4_USERNAME / GPSS4_PASSWORD not set`（既有訊息，沿用） | 帳號池為空（無任何成對完整帳號） | raise `GPSS4LoginError` | 於 `.env` 設定 `GPSS4_USERNAME`/`GPSS4_PASSWORD`（或 `_N` 組） |

## Notes

- 登入失敗（rotation 觸發）與「session 過期 re-login」嚴格區分（DD-6）：後者用當前有效帳號重登，不輪替。
- 登入模式不燒 API quota，無「額度用盡」語義——與 REST rotation（`patentmcp/gpss-account-rotation`）的觸發條件不同。
