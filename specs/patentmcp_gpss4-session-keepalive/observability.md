# Observability: patentmcp_gpss4-session-keepalive

## Events

- `session.mint`：mint 新 GPSS4 session 並登入成功時,記 holder + 時戳(這是唯一燒登入
  額度的事件——監看它的頻率即監看帳號鎖定風險)。
- `session.reuse`：acquire 復用既有 session(不重登)時,記 age + idle 時間。
- `session.release`：release keep-alive(不 close)時。
- `session.busy_refused`：並發 acquire 被 fail-fast(§4A)時,記被拒 holder + 現 holder。
- `session.reap`：reaper 回收時,記原因(`idle_ttl` / `absolute_ttl` / `health_fail`)+ age。
- `session.close_explicit`：顯式 `gpss4_session_close` 時,記 was_busy。
- `session.health_fail`：復用前健康檢查失敗、觸發重建時。

## Metrics

- `login_count`（累積）：process 生命期內實際登入次數。**核心指標**——keep-alive 成功
  的直接證據是「N 次登入模式呼叫 → login_count ≪ N」。
- `reuse_ratio`：`session.reuse / (session.reuse + session.mint)`,越高越省額度。
- `session_age_sec` / `session_idle_sec`：現 live session 壽命 / 閒置(status tool 即時查)。
- `busy_refused_count`：§4A fail-fast 次數(健康的低值;突增代表有並發誤用)。
- `reap_reason 分佈`：idle vs absolute vs health_fail 佔比(調 TTL 的依據)。

## 可觀測入口

- `gpss4_session_status` tool：即時查 live / busy / holder / age / idle / expires_in。
- 事件寫入既有 logger（`logging.getLogger("patent_mcp_server.gpss4.session_manager")`），
  沿用 login_gate 的 warning 風格;不新造 log 基礎設施。
