# Observability: patentmcp_search-dispatcher

## Events

- `patentmcp.search.dispatch` log line(INFO):每次 `patent_search` 呼叫記 QuerySpec 摘要(軸名單,不含值)+ 最終 source + 各級 status(= provenance 的 log 投影)。
- `patentmcp.search.scraping_gate` log line(WARNING):`SCRAPING_REQUIRED` 觸發時記官方三級 miss 原因;`allow_scraping=True` 放行時記 `scraping=true`。
- 每級 backend error(WARNING):`source / http code / reason`,與 provenance 同源。

## Metrics

- provenance 本身即 per-call metrics:`elapsed_ms` 每級耗時、`status` 分佈。
- 無獨立 metrics pipeline(與 repo 現況一致);稽核走 log + provenance 回傳值,`search_audit` 工具可離線彙整 matrix-log。
