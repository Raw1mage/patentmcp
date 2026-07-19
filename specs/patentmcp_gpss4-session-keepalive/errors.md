# Errors: patentmcp_gpss4-session-keepalive

## Error Catalogue

| Code | Condition | Surface | Recovery |
| ---- | --------- | ------- | -------- |
| `GPSS4LoginBusyError` | `acquire` 時已有 in-use holder (§4A 禁並發) | raise;帶現 holder + held_for + exe | 不排隊不重試;等現有工作結束再重派 |
| `GPSS4_LOGIN_BUSY` | 上者在 4 進入點被捕捉後的 typed error | tool 回 `{success:false, error_code}` | 呼叫端稍後重試(承接既有契約,不回歸) |
| `GPSS4LoginError` | mint 新 session 登入失敗(CAPTCHA/帳號池耗盡) | raise(session.py 既有) | 帳號輪替已在 login() 內;全池失敗才 raise |
| `GPSS4DbScopeError` | scope 設定失敗(承接 BR_20260719 DD-6) | raise → batch 中止 | fail-fast,絕不用可能錯 scope 續查 |
| `SESSION_HEALTH_FAILED` | 復用前健康檢查失敗(member 頁不可達 / redirect-to-login) | 內部訊號 → close + mint | 自動乾淨重建;不靜默續用(DD-6 無 fallback) |
| `SESSION_TTL_EXPIRED` | idle / absolute TTL 逾時 | 內部訊號 → reap close | 下次 acquire 走 mint 重建 |

## 非錯誤(正常回收路徑)

- 顯式 `gpss4_session_close`:正常歸還,回 `{closed:bool, was_busy:bool}`;`was_busy=true`
  為異常訊號(close 了正被持用的 session)但仍執行。
- reaper 回收:idle/absolute TTL 逾時的靜默 close,記 observability 事件,非錯誤。
