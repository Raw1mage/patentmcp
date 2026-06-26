# Design: patentmcp_mcp-standard-conformance

## Context

patentmcp is a vendored MCP (`vendor/patents-mcp/`) serving USPTO / Google
Patents / TIPO GPSS / EPO OPS patent data over UDS streamable-http, with a
token-based file store. Recon (2026-06-25, read not memory):

- **webctl.sh** (`vendor/patents-mcp/webctl.sh`) is already a first-class wrapper:
  `start|stop|restart|refresh|health|clean|purge` + `ensure_socket_dir` +
  `wait_healthy` (docker health-status poll). R7.1/R7.2/R7.3 satisfied.
- **HTTP app** (`vendor/patents-mcp/src/patent_mcp_server/_http_app.py`,
  `build_app`) mounts FastMCP `/mcp` and appends: `/` (HTML landing, lists tools
  via `mcp.list_tools()`), `/healthz` (`{ok, service, store}`),
  `/files/{token}/blob/{rel}`, `/skills/{name}.zip`.
- **R2/R4/R9/R10/R1** already conformant.

The only gaps: R8.1 (no JSON `/tools`), R8.3 (health path is `/healthz` not the
standard `/health`), R7.4 (no self-heal script).

## Goals / Non-Goals

### Goals

- Close R8 (`/tools` + `/health`) and R7.4 (self-heal) **additively**.
- Source `/tools` from the live registry (single source) — same `mcp.list_tools()`
  the landing page already calls.

### Non-Goals

- Rewriting webctl.sh (already first-class).
- Transport / UDS / file-transfer / skillPaths changes (already conformant).
- Touching patent search/retrieval tool logic.
- opencode host-side changes (`harness_plugin-extension-points`).

## Decisions

- **DD-1**: `GET /tools` returns `{tools: [...]}` sourced from `await
mcp.list_tools()` (the same call `landing` already makes), serialized to JSON.
  No hand-maintained copy → single source of truth, zero drift.
- **DD-2**: `GET /health` is added as a **new route returning the same handler
  payload** as `/healthz` (`{ok, service, store: store.stats()}`). `/healthz`
  stays registered as a back-compat alias — both point at the same `health`
  coroutine (no duplicated logic).
- **DD-3**: Both new routes are appended in `build_app`'s
  `app.router.routes.extend([...])` block, alongside the existing landing /
  healthz / blob / skill routes — minimal, localized change.
- **DD-4**: `GET /tools` serialization handles FastMCP `Tool` objects by
  projecting `{name, description, inputSchema}` (mirroring how other fleet repos'
  `/tools` shape it), guarding against non-serializable fields. Fail-loud on
  registry error (mirror landing's try/except but return 500 JSON, not silent []).
- **DD-5**: Self-heal script lives at `vendor/patents-mcp/scripts/patentmcp-self-heal.sh`
  (next to the vendored webctl.sh it complements), idempotent `--check`/`--heal`,
  probes the UDS socket existence (matching webctl's `health` semantics), recreates
  only patentmcp's own compose project (`patentmcp-${USER}`), never spawns a
  competing daemon (`scripts/docxmcp-self-heal.sh` reference shape).
- **DD-6**: Self-heal probes the **UDS socket** (patentmcp's actual transport),
  not an HTTP port — consistent with webctl.sh's `health` which checks `[ -S
"$SOCKET" ]`. Optionally curls `/health` over the socket as a deeper check.

## Risks / Trade-offs

- **R-1**: `/tools` serialization of FastMCP Tool objects may include
  non-JSON-native fields. Mitigation: DD-4 explicit projection of
  `{name, description, inputSchema}`.
- **R-2**: Landing page swallows registry errors (`except: tools=[]`). For
  `/tools` that would be a silent-fallback violation (user 天條). Mitigation:
  DD-4 fail-loud 500 on registry error.
- **R-3**: Self-heal recreating the wrong compose project. Mitigation: DD-5 pins
  `patentmcp-${USER}` project name exactly as webctl.sh does.

## Critical Files

- `vendor/patents-mcp/src/patent_mcp_server/_http_app.py` — `build_app` route
  table (existing `health` coroutine ~L261; `routes.extend` ~L291).
- `vendor/patents-mcp/webctl.sh` — reference for project name + socket path (read,
  not modified).
- `vendor/patents-mcp/scripts/` — new self-heal script location.
- `vendor/patents-mcp/mcp.json` — instructions note.
- `README.md` — endpoint docs.
