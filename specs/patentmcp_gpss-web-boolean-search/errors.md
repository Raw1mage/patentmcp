# Errors: patentmcp_gpss-web-boolean-search

<!-- error catalogue for gpss_web_search (人類路徑布林檢索工具) -->

## Error Catalogue

| Code | Condition | Surface | Recovery |
| ---- | --------- | ------- | -------- |
| `INVALID_PARAMS` | 檢索式語法非法：欄位代碼不在白名單、`@欄位`後綴格式錯、括號不配對、日期語法錯 (DD-5) | `{success:false, error_code:"INVALID_PARAMS", hint:<明細>}`；**零網路呼叫** | 依 hint 修正檢索式；參照 `knowledge-base/gpss-search-syntax/` 欄位代碼表 |
| `GPSS_WEB_HANDSHAKE_FAILED` | gpss3 handshake 後 INFO token 抽取失敗 (portal/session 異常，DD-1) | `{success:false, error_code:"GPSS_WEB_HANDSHAKE_FAILED"}`；不靜默回空結果 | 稍後重試 (Cloudflare cooldown 後)；檢查 gpss3 站點可用性 |
| `GPSS_WEB_RESULT_TOO_BROAD` | 總命中觸及 GPSS 模糊上限 (>30萬)，母數無意義 (DD-4) | `{success:false, error_code:"GPSS_WEB_RESULT_TOO_BROAD", hint:"加日期/國別/收窄布林"}`；不回 records | 加 `date_from`/`date_to`、指定 `databases` 國別、收窄布林同義詞群 |
| `GPSS_WEB_POLL_TIMEOUT` | `ttsserv_watch` 輪詢逾時 (達最大次數仍有庫未就緒，DD-3/DD-6) | `{success:true, totals:<部分>, partial:true, pending_databases:[...]}`；明示哪些庫仍檢索中 | 接受部分就緒結果，或稍後重查未就緒庫 |

## 錯誤處理原則 (使用者天條對齊)

- **fail-fast、不新增 fallback**：語法錯 / handshake 失敗 / 母數過大一律顯式報錯，不靜默降級、不猜測續跑。
- **零網路呼叫早退**：`INVALID_PARAMS` 在 handshake 前擋下，省一次 Cloudflare 節流預算。
- **部分就緒誠實回報**：輪詢逾時回 `partial:true` + `pending_databases`，不假裝完整 (對齊官方非同步語義)。
- **絕不誤呼叫 API**：本工具走網頁路徑，任何路徑不得 fallback 到 `gpss_api` REST 燒 quota。
