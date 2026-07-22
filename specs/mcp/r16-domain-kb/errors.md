# Errors: mcp_r16-domain-kb

## Error Catalogue

| Code | Condition | Surface | Recovery |
| ---- | --------- | ------- | -------- |
| `KB_UNAVAILABLE` | `PATENTS_KB_DB` 未設、檔案不存在、或 sqlite 開啟失敗 | `{"success": false, "error_code": "KB_UNAVAILABLE", "message": "<reason>", "remedy": "KB lives host-side at <repo>/.specbase/ragbase.sqlite; distill via specbase producer.ts (ragbase_distill); mount is live, no restart needed."}` | 依 remedy 在 host 端補 KB / 修掛載；工具可即時重試（連線 per-request） |
| `KB_BAD_QUERY` | q 為空字串或全空白；kb_get 的 id 為空 | `{"success": false, "error_code": "KB_BAD_QUERY", "message": "empty query"}` | caller 補 q/id 重呼叫 |
| `KB_OBJECT_NOT_FOUND` | kb_get 的 id 不存在 | `{"success": false, "error_code": "KB_OBJECT_NOT_FOUND", "message": "<id> not found. consider: patentmcp_kb_query"}` | 先 kb_query 找正確 id |
| `KB_READONLY_VIOLATION` | （防禦性）任何寫入嘗試觸及 query_only 連線 | sqlite OperationalError 原樣上拋，不吞 | 不應發生；發生即 bug，report issue |
