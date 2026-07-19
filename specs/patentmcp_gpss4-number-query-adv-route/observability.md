# Observability: patentmcp_gpss4-number-query-adv-route

## Events

- `GPSS4 login gate acquired by <tool> at <ts>` — login gate 取得（§4A DD-7 可觀測）。
- `GPSS4 login gate released (held <duration>s)` — gate 釋放（finally）。
- `GPSS4 login gate BUSY: held by <holder> since <ts>` — 拿不到 gate fail-fast。
- `GPSS4 search db scope set to <codes> (persist=<bool>)` — scope 設定（既有 log，per-session 首次）。
- `GPSS4 scope reused for session (already <codes>)` — per-session 復用跳過設定（DD-4）。
- `gpss4_resolve_appnos: resolved=<n> not_found=<n> unmatched=<n> via_adv=<n>` — batch 收尾統計。

## Metrics

- `resolved_rate` — batch 中成功解析出 pub_no 的比率（本 BR 核心驗收：從 0 回升）。
- `unmatched_rate` — 命中卻抽不到號的比率（本 BR 主症狀，改 adv 後應趨近 0）。
- `scope_set_count_per_session` — 每 session 實際 set_search_databases 次數（DD-4 驗證：
  應 = 涉及的國別數，而非 query 筆數）。
- `login_gate_busy_count` — gate 拒斥次數（並發嘗試被擋 = §4A 生效證據）。
- `effective_db_scope`（每次查詢回傳欄位）— 讓上層判別 unmatched 是真無還是 scope 沒開。
