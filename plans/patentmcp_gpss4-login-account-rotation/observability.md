# Observability: patentmcp_gpss4-login-account-rotation

## Events

- `logger.info("gpss4 login attempt %d: %s", ...)` — 既有單帳號 CAPTCHA 重試 log（保留）。
- `logger.warning("gpss4 account #%d login failed, rotating to next", idx)` — 某帳號登入失敗並輪替時。
- `logger.error("gpss4 all %d accounts failed to login", n)` — 全部帳號登入失敗 fail-fast 時。

## Metrics

- 帳號輪替次數（推算）— 由 warning log 計數，反映主帳號登入健康度。
- 各帳號 `驗證碼錯誤` 旗標 — 區分 CAPTCHA 抖動 vs 帳密真錯的訊號。
