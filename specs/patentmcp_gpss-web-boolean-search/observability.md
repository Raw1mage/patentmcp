# Observability: patentmcp_gpss-web-boolean-search

<!-- observability plan for gpss_web_search -->

## Events

- `gpss_web_search.start` — 工具被呼叫時；記 expr (脫敏長度)、date_from/to、databases。
- `gpss_web_search.syntax_rejected` — 語法驗證失敗；記非法明細 (欄位代碼 / 括號 / 日期)，確認零網路呼叫早退。
- `gpss_web_search.handshake` — gpss3 handshake 完成 / 失敗；記 INFO token 是否抽取成功、action URL。
- `gpss_web_search.post` — 單一檢索式 POST 完成；記 `query_applied` (含併入的 ID= 日期)、patDB 國別。
- `gpss_web_search.poll` — 每次 `ttsserv_watch` 輪詢；記輪詢輪次、各庫就緒狀態。
- `gpss_web_search.too_broad` — 母數 >30萬 fail-fast；記觸發的檢索式，供後續分析哪類 query 易過寬。
- `gpss_web_search.done` — 回傳；記 grand_total、各庫命中數、records 筆數、耗時。

## Metrics

- `gpss_web_search_calls_total{result}` — 呼叫次數，依 result (success / invalid_params / handshake_failed / too_broad / poll_timeout) 分維。
- `gpss_web_search_poll_rounds` — 每次檢索的 `ttsserv_watch` 輪詢輪次分布 (偵測輪詢效率 / 逾時傾向)。
- `gpss_web_search_latency_seconds` — 端到端耗時 (handshake + POST + 輪詢)，用於節流預算調校。
- `gpss_web_search_grand_total` — 命中母數分布 (偵測 too_broad 觸發頻率，判斷是否需調整限縮提示)。
- `gpss_api_quota_saved` (推算) — 走網頁路徑而非 API 的檢索次數 × 估算 API 額度，量化省額度效益。

## 節流健康觀測

- `_GPSS_POLICY` cooldown 觸發次數 — Cloudflare Managed Challenge 命中訊號；上升代表節流參數需放寬。
- 序列化佇列深度 — 確認所有 gpss3 請求 (含輪詢) 未並行觸發 Challenge。
