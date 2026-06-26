# Tasks: patentmcp_mcp-standard-conformance

Narrow additive conformance: R8 introspection (`/tools` + `/health`) + R7.4
self-heal. webctl / R1 / R2 / R4 / R9 already conformant (out of scope). All
edits land under the patentmcp repo (`vendor/patents-mcp/`); restart via its own
`webctl.sh refresh`.

## 1. R8 — Tool introspection (`GET /tools`)

- [x] 1.1 Add `GET /tools` route in `_http_app.py` `build_app`, sourcing schemas
      from `await mcp.list_tools()` (single source; DD-1).
- [x] 1.2 Project each Tool to `{name, description, inputSchema}` JSON; fail loud
      (500 JSON) on registry error — no silent `[]` fallback (DD-4).

## 2. R8 — Standard health path (`GET /health`)

- [x] 2.1 Register `GET /health` pointing at the existing `health` coroutine
      (same `{ok, service, store}` payload; DD-2).
- [x] 2.2 Keep `GET /healthz` registered as a back-compat alias (no logic dup).

## 3. R7.4 — Idempotent self-heal script

- [x] 3.1 Add `vendor/patents-mcp/scripts/patentmcp-self-heal.sh` (`--check`/
      `--heal`), probing the UDS socket; recreate only the `patentmcp-${USER}`
      compose project when unhealthy; never spawn a competing daemon (DD-5/6).
- [x] 3.2 `bash -n` + `--help` smoke; `command -v docker` precheck guard.

## 4. Manifest + docs

- [x] 4.1 Update `vendor/patents-mcp/mcp.json` instructions to note `/tools` +
      `/health` + self-heal.
- [x] 4.2 Update patentmcp `README.md` with the new endpoints.
- [x] 4.3 Update the fleet gap matrix row for patentmcp in
      `opencode/specs/mcp-integration-standard/standard.md` once landed.
      DONE: matrix row (§12 R7→webctl+self-heal, R8→`/tools`+`/health`), per-repo
      delta (now ✅ fully conformant), and §14 downstream (moved to DONE) all
      synced in the opencode repo on user instruction.

## 5. Validation

- [x] 5.1 V1 — `GET /tools` returns JSON schemas matching `mcp.list_tools()`
      (acceptance 1). Live: 18 tools, keys {name,description,inputSchema}.
- [x] 5.2 V2 — `GET /health` returns liveness; `GET /healthz` still works
      (acceptance 2). Both return identical `{ok,service,store}`.
- [x] 5.3 V3 — self-heal `--check`/`--heal` idempotent, no competing daemon
      (acceptance 3). `--check` exit 0 healthy; `--heal` no-op when healthy.
- [x] 5.4 V4 — existing surfaces unchanged: `/mcp`, `/files/{token}/blob/{rel}`,
      `/skills/{name}.zip`, landing `/`, webctl verbs (acceptance 4). landing
      200, skill zip 200 application/zip, /healthz 200.
- [x] 5.5 V5 — restart patentmcp via its own `webctl.sh refresh`; live smoke all
      endpoints over the UDS socket. Rebuild OK, container healthy, all green.
- [x] 5.6 V6 — event_record + mcp.json/README sync (acceptance 5). gap-matrix
      (opencode repo) deferred per cross-repo rule — see 4.3.
