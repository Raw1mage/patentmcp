# Proposal: patentmcp_mcp-standard-conformance

## Why

patentmcp is the next MCP to bring into full conformance with the fleet
integration standard (`opencode/specs/mcp-integration-standard/standard.md`).
Recon (read 2026-06-25, not memory) **shrinks the gap matrix's headline claim**:

- The gap matrix marked R7 as "⚠️ vendored" — but `vendor/patents-mcp/webctl.sh`
  is **already a first-class webctl** (`start|stop|restart|refresh|health|clean|
purge` + `ensure_socket_dir` + `wait_healthy`). R7.1/R7.2/R7.3 are satisfied.
- R8 was marked "⚠️ landing page" — accurate. The HTTP app (`_http_app.py`) has a
  `/healthz` JSON endpoint (`{ok, service, store}`) and an HTML landing page that
  lists tools, but **no machine-readable `GET /tools`** and the health path is
  `/healthz`, not the standard `/health`.

So the real, narrow gaps are two-and-a-half:

1. **R8.1** — add `GET /tools` JSON (authoritative tool schemas).
2. **R8.3** — expose `GET /health` (standard path) alongside the existing
   `/healthz` (kept as alias).
3. **R7.4** — add an idempotent host-side self-heal script (`--check`/`--heal`),
   the one R7 sub-clause the otherwise-complete webctl lacks.

## Original Requirement Wording (Baseline)

- "從需求的即時性來說，先patentmcp，再bodesign" — prioritise patentmcp before
  bodesign in the fleet top-up sequence.

## Requirement Revision History

- 2026-06-25: initial draft via plan-init.ts
- 2026-06-25: scope set from recon — R8 (`/tools` + `/health`) + R7.4 self-heal;
  R7 webctl already first-class (no rewrite). User chose full plan-builder lifecycle.

## Effective Requirement Description

1. **R8.1**: add `GET /tools` returning authoritative current tool schemas,
   sourced from the live FastMCP registry (`mcp.list_tools()`, same source the
   landing page already uses) — no hand-maintained copy.
2. **R8.3**: add `GET /health` (standard liveness/readiness path) returning the
   same payload as the existing `/healthz`; keep `/healthz` as a back-compat alias.
3. **R7.4**: add an idempotent self-heal script under the patentmcp repo
   (`--check`/`--heal`) that probes the UDS socket / health, recreates only
   patentmcp's own compose service when unhealthy, and never spawns a competing
   daemon (`scripts/docxmcp-self-heal.sh` reference shape).

## Scope

### IN

- R8.1 `GET /tools` JSON from live registry.
- R8.3 `GET /health` standard path (+ `/healthz` alias retained).
- R7.4 idempotent self-heal script.
- Manifest `instructions` + README note for the new endpoints.

### OUT

- **Rewriting webctl.sh** — it is already first-class (R7.1/R7.2/R7.3 met);
  only the self-heal sub-clause (R7.4) is added.
- **Transport / UDS changes** — patentmcp's UDS streamable-http is already
  R1-conformant.
- **R2 file-transfer** — already conformant (token model + `/files/{token}/blob/{rel}`).
- **R9 skillPaths** — already conformant (`["../../skills"]` + `/skills/{name}.zip`).
- **Tool-surface / search-logic changes** — patent search/retrieval tools untouched.
- **opencode host-side changes** — host consumption is `harness_plugin-extension-points`.

## Non-Goals

- Re-architecting the vendored `patents-mcp` package structure.
- Changing the FastMCP transport or the gateway prefix behavior.

## Constraints

- **Additive, back-compat by construction** — `/healthz` stays; new routes only add.
- **No fallback** (user 天條) — new endpoints fail loud; no silent defaults.
- **Single source for `/tools`** — sourced from `mcp.list_tools()`, never a copy.
- **patentmcp is a live MCP** — changes land in its repo; restart via its own
  `webctl.sh refresh`, never spawn competing daemons.
- **Vendored structure** — edits land under `vendor/patents-mcp/`; respect its layout.

## What Changes

- `vendor/patents-mcp/src/patent_mcp_server/_http_app.py` — add `GET /tools` +
  `GET /health` routes (in `build_app`, alongside the existing `/healthz`).
- `vendor/patents-mcp/scripts/` (or repo `scripts/`) — new idempotent self-heal script.
- `vendor/patents-mcp/mcp.json` — `instructions` note the new endpoints.
- patentmcp `README.md` — document `/tools` + `/health` + self-heal.

## Capabilities

### New Capabilities

- **Introspection**: `GET /tools` (machine-readable schemas) + `GET /health`
  (standard liveness path).
- **Self-heal**: idempotent `--check`/`--heal` recovery script.

### Modified Capabilities

- Health surface gains the standard `/health` path while `/healthz` remains.

## Impact

- Affected code: `_http_app.py`, a self-heal script, `mcp.json`, README.
- Operators: standard `/health` probe + self-heal become available; `/healthz` unchanged.
- Consumers: existing `/mcp`, `/files`, `/skills`, `/healthz`, landing page unchanged.
- Docs: fleet gap matrix row for patentmcp updates once landed.
