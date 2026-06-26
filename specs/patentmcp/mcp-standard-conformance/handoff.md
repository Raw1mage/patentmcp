# Handoff: patentmcp_mcp-standard-conformance

## Execution Contract

Narrow additive conformance: R8 introspection (`/tools` + `/health`) + R7.4
self-heal. All edits land in the **patentmcp repo** under `vendor/patents-mcp/`;
restart via its own `webctl.sh refresh`, never spawn a competing daemon. Every
change is additive — no existing consumer (`/mcp`, `/files`, `/skills`,
`/healthz`, landing page, webctl verbs) may break.

## Required Reads

- `spec.md` — R1-R3 requirements + 5 acceptance checks
- `design.md` — DD-1..DD-6 (`/tools` from `mcp.list_tools()`, `/health` aliasing
  `/healthz`, self-heal probing UDS socket, fail-loud no silent `[]`)
- `opencode/specs/mcp-integration-standard/standard.md` §R8 / §R7.4 — contract
- patentmcp `vendor/patents-mcp/src/patent_mcp_server/_http_app.py` (`build_app`,
  existing `health` coroutine ~L261, `routes.extend` ~L291), `webctl.sh`
  (project name `patentmcp-${USER}`, socket path)

## Stop Gates In Force

- **Restart gate**: V5 live smoke needs `webctl.sh refresh` (rebuild + recreate),
  which interrupts in-flight patentmcp requests. patentmcp is a separate live MCP,
  NOT the opencode daemon — restart via its own webctl / docker compose, never
  restart_self.
- **No-fallback (user 天條)**: `/tools` fails loud (500 JSON) on registry error;
  no silent `[]` like the landing page does.
- **Back-compat gate**: acceptance 4 (existing surfaces unchanged) MUST pass.

## Coordination

- **Standard source**: `mcp-integration-standard` (living, graduated to
  `opencode/specs/`) — its gap matrix row for patentmcp updates once this lands.
- **Sibling sequence**: bodesign is next after patentmcp (user-set order).
- **Host-side**: `harness_plugin-extension-points` (done) — no host change here.

## Execution-Ready Checklist

- [ ] Read `_http_app.py` `build_app` route block before editing (don't assume)
- [ ] Confirm `mcp.list_tools()` Tool object shape for `/tools` projection
- [ ] Confirm `webctl.sh` project name + socket path for the self-heal script
- [ ] After edits: `webctl.sh refresh` + live smoke all endpoints over UDS (V5)
- [ ] event_record + mcp.json/README/gap-matrix sync (V6)
