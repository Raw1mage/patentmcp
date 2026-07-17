# Errors: patentmcp_gpss-account-rotation

## Error Catalogue

| Code | Condition | Surface | Recovery |
| ---- | --------- | ------- | -------- |
| `GPSS_ALL_ACCOUNTS_EXHAUSTED` | 帳號池所有帳號本次 process 皆已判定額度用盡（DD-5） | `{success:false, error_code:"GPSS_ALL_ACCOUNTS_EXHAUSTED", error:"...", accounts_tried:N}` | 稍後重試（等 GPSS 時段配額重置；下班/週末為寬 30,000 時段）或於 `GPSS_USER_CODES` 增設更多帳號 |
| `GPSS_USER_CODE not set`（既有訊息，沿用） | 帳號池為空（`GPSS_USER_CODES` 與 `GPSS_USER_CODE` 皆未設定） | `{success:false, error:"GPSS_USER_CODE not set..."}` | 於 `.env` 設定 `GPSS_USER_CODES` |

## Notes

- 額度用盡（`GPSS_ALL_ACCOUNTS_EXHAUSTED`）與「查無資料」嚴格區分（DD-2）：查無資料仍走既有 `success:false + message` 回傳，不進 rotation、不冒充帳號用盡。
