# Observability: patentmcp_r17-minimum-operational-toolset

## Events

- `resources/read` + `resources/list` land `category="access"` rows in the unified
  observability store (`/patentdb/observability.sqlite`) via the existing pure-ASGI
  access-log middleware (no new logging path — resource reads over HTTP are already observed).
- `cache_export` preflight failures (`EXPORT_EMPTY` / `ASSERTION_FAILED`) are typed
  tool envelopes; the central `@mcp.tool` exception choke point already records uncaught
  exceptions. Explicit `record_friction(kind="silent")` may be added if a preflight becomes
  a warn+continue path (it does not — it fail-loud returns).

## Metrics

- resource retrieval share: `SELECT count(*) FROM events WHERE category='access' AND uri LIKE '%resources%'`
  — proxy for portable-floor egress adoption vs `/files/blob`.
- delivery-gate rejections: count of `EXPORT_EMPTY` / `ASSERTION_FAILED` (via tool-result
  inspection in tests / friction log if promoted) — proves empty artifacts are refused, not landed.
