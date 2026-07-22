# Observability: patentmcp_gpss-account-rotation

## Events

- `logger.warning("GPSS account %d quota exhausted (over download quantity), rotating to next", idx)` — 偵測到某帳號額度用盡並輪替時。
- `logger.error("GPSS all %d accounts exhausted", n)` — 全部帳號用盡 fail-fast 時。

## Metrics

- 帳號輪替次數（推算）— 由 warning log 計數，反映當前時段配額壓力。
- `accounts_tried`（回傳欄位）— 全部用盡時已嘗試帳號數，等於帳號池大小，供呼叫端判斷是否需擴充帳號。
