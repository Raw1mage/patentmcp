# Spec: patentmcp_mcp-standard-conformance

## Purpose

Bring patentmcp to full conformance with the fleet integration standard
(`opencode/specs/mcp-integration-standard/standard.md`) by closing its narrow
remaining gaps — R8 introspection (`/tools` + `/health`) and the R7.4 self-heal
sub-clause — **additively**, breaking no existing consumer. patentmcp's webctl,
transport (R1), file-transfer (R2), naming (R4), and skillPaths (R9) are already
conformant and out of scope.

## Requirements

### Requirement: R1 — Machine-readable tool introspection (standard R8.1)

patentmcp MUST expose authoritative tool schemas over HTTP, not only via the
HTML landing page.

#### Scenario: GET /tools returns live schemas

- **GIVEN** a running patentmcp service
- **WHEN** a client `GET /tools`
- **THEN** patentmcp returns JSON of its current tool schemas sourced from the
  live FastMCP registry (`mcp.list_tools()`)
- **AND** the payload reflects the same tools the landing page lists (single source)

### Requirement: R2 — Standard health path (standard R8.3)

patentmcp MUST expose the standard `/health` liveness path while keeping its
existing `/healthz`.

#### Scenario: GET /health returns liveness

- **WHEN** a client `GET /health`
- **THEN** patentmcp returns a liveness/readiness JSON payload (`{ok, service, store}`)
- **AND** the existing `GET /healthz` continues to return the same payload (alias)

### Requirement: R3 — Idempotent self-heal (standard R7.4)

patentmcp MUST ship an idempotent host-side self-heal script — the one R7
sub-clause its otherwise-complete webctl lacks.

#### Scenario: self-heal check and heal

- **GIVEN** a self-heal script with `--check` / `--heal`
- **WHEN** invoked repeatedly
- **THEN** it probes the UDS socket / health, recreates only patentmcp's own
  compose service when unhealthy, is idempotent, and never spawns a competing daemon

## Acceptance Checks

1. `GET /tools` returns JSON tool schemas matching `mcp.list_tools()`.
2. `GET /health` returns the liveness payload; `GET /healthz` still works (alias).
3. The self-heal script `--check`/`--heal` is idempotent and never spawns a
   competing daemon.
4. Existing surfaces unchanged: `/mcp`, `/files/{token}/blob/{rel}`,
   `/skills/{name}.zip`, the landing page `/`, and `webctl.sh` verbs all still work.
5. `mcp.json` instructions + README document the new endpoints; the fleet gap
   matrix row for patentmcp updates to fully-conformant once landed.
