# Observability: patentmcp_mcp-standard-conformance

## Events

- `tools.introspection.served` — `GET /tools` returned N schemas (count, duration_ms).
- `tools.introspection.error` — registry error surfaced as 500 (fail-loud signal, not swallowed).
- `health.served` — `GET /health` or `/healthz` liveness returned (path, ok).
- `selfheal.check` — self-heal probe result (healthy bool).
- `selfheal.heal` — self-heal recreated the compose project (action, duration_ms).

## Metrics

- `patentmcp_tools_requests_total{outcome=ok|error}` — /tools call volume + error rate.
- `patentmcp_health_requests_total{path=health|healthz}` — liveness probe split (observe alias usage).
- `patentmcp_selfheal_runs_total{mode=check|heal,result=healthy|recreated}` — self-heal activity.

## Logs

- /tools registry errors logged at ERROR with the exception (never silently `[]`).
- self-heal logs each step prefixed `[patentmcp-self-heal]` (docxmcp-self-heal convention).

## Alerts

- Sustained `patentmcp_tools_requests_total{outcome=error}` > 0 → registry fault, investigate.
- `patentmcp_selfheal_runs_total{result=recreated}` spiking → service instability upstream of self-heal.
