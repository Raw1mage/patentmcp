# Observability: patentmcp_webdav-r13-refactor

## Events

- DAV 每個 method 一行 audit log：`[dav] <method> <subject> <rel> owner=<id> status=<code>`（沿用 token store 審計風格）
- provision/export/close 各一行：`[cache] provision|export|close subject=<id> owner=<id> result=<ok|error_code>`
- reaper 決策：`[reaper] skip(deliverable-dirty)|reap(ephemeral)|warn(safety-net)` 含 token/idle 秒數
- TOOL_LANDED 命中：`[landed] tool=<name> caller-redirected`（量測遷移進度，決定 0.5.0 移除時機）
- landing scripts stderr 單行結構化：`[script] verb=<v> status=<ok|error_code> elapsed_ms=<n>`

## Metrics

- dav_requests_total{method,status} — DAV 面使用量與錯誤率
- cache_active{class} — 存活 cache 數（ephemeral vs deliverable）
- cache_dirty_age_seconds — 未落地 dirty 持續時間（safety-net 前兆）
- tool_landed_hits_total{tool} — redirect 命中次數
