# Errors: patentmcp_webdav-r13-refactor

## Error Catalogue

| Code | Condition | Surface | Recovery |
| ---- | --------- | ------- | -------- |
| `TOOL_LANDED` | 呼叫已落地下架的 container tool | MCP result `{success:false, error_code, landing:{script,usage}}` | 改用指引的 landing script |
| `MISSING_DEPENDENCY` | landing script 缺 poppler/matplotlib 等 host 依賴 | script typed JSON + exit≠0 | 安裝依賴後重跑；不降級 |
| 401 + `WWW-Authenticate` | DAV 無/錯 Basic credential | HTTP 401 | 用 provision 回傳的 credential；無 fallback |
| 403 | 跨 owner 存取 / owns() 失敗 | HTTP 403，零 bytes | 確認 subject 歸屬；不臆測他人 token |
| 423 | LOCK 衝突 | HTTP 423 Locked | 等 lock TTL 或 UNLOCK |
| `WORKSPACE_CLOSE_DIRTY` (409) | close 時存在未 export 的 dirty 改動 | HTTP 409 + 未落地清單 | 先 cache_export；或顯式 force |
| `EXPORT_TARGET_UNREACHABLE` (502) | export target 父目錄不存在/不可寫 | HTTP 502 | 修正 target；不臆造目錄 |
| traversal rejection | rel 路徑逃逸 token dir | typed 4xx | 修正相對路徑 |
| `PURE_LIB_DRIFT` | vendored _lib 與 src/_pure hash 不一致 | CI test fail | 重跑 vendor 同步 |
