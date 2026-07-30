# Spec: patentmcp_mcp-standard-conformance

## Purpose

Bring patentmcp to full conformance with the fleet integration standard
(`opencode/specs/mcp-integration-standard/standard.md`) by closing its narrow
remaining gaps — R8 introspection (`/tools` + `/health`), the R7.4 self-heal
sub-clause, and the R9.2 skill-shipping LIST half — **additively**, breaking no
existing consumer. patentmcp's webctl, transport (R1), file-transfer (R2) and
naming (R4) are already conformant and out of scope.

R9 was ALSO listed as out-of-scope here until BR_20260730, on the strength of
`skillPaths` being declared in `mcp.json` and `/skills/patentworks.zip` serving
200. That reading conflated the two halves of R9: `skillPaths` is *in-repo*
discovery for a host that has an `appRoot`, while a remote client has none and
must discover names over HTTP. patentmcp served the download half only, under a
route with the skill name f-string'd into the pattern, so a generic consumer's
`list → download by name` flow died at step one on a 404 that looks exactly like
"this service ships no companion". **This spec now pins BOTH halves** — the gap
existed precisely because no clause named the list endpoint (§R4 below), so the
self-check kept coming back green.

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

### Requirement: R4 — Companion-skill shipping, BOTH halves (standard R9.2)

patentmcp MUST make its companion skill **discoverable**, not merely
downloadable. Declaring `skillPaths` in `mcp.json` satisfies only in-repo
discovery for a host that can resolve a relative path against an `appRoot`; a
client reaching this server over the socket has no `appRoot` and can only learn
what exists by asking. Serving a zip under a route whose pattern hard-codes one
skill name is therefore NOT conformance — it requires the client to already know
the answer it came to ask (BR_20260730).

#### Scenario: GET /skills lists companion skills by bare name

- **GIVEN** a running patentmcp service with a non-empty `skills/` tree
- **WHEN** a client `GET /skills` with no prior knowledge of any skill name
- **THEN** patentmcp returns 200 with a JSON list whose elements are **bare skill
  names** (`patentworks`), never filenames (`patentworks.zip` — a filename makes
  the consumer request `patentworks.zip.zip`)
- **AND** the list is derived from the `skills/` tree, so adding a second
  companion requires no code change
- **AND** an absent or empty tree returns 200 with an empty list — an honest
  "no companion", distinguishable from a transport error

#### Scenario: GET /skills/{name}.zip serves any listed name

- **WHEN** a client downloads each name returned by `GET /skills`
- **THEN** every one returns 200 with a well-formed archive whose member count
  matches the `file_count` advertised in the list
- **AND** an unknown name returns a typed 404 — never a 500, and never a 200
  carrying an empty archive
- **AND** a traversal attempt (`..`, `a/b`, percent-encoded escapes) is rejected
  by both the safe-name rule and a containment check on the resolved path

#### Scenario: archive hygiene (standard R9.7.1)

- **WHEN** an archive is produced
- **THEN** no member carries an absolute path, a `..` segment, or a symlink, and
  compiled bytecode (`.pyc`/`.pyo`, `__pycache__`) is excluded — it is
  interpreter-specific and leaks absolute build paths through `co_filename`

## Acceptance Checks

1. `GET /tools` returns JSON tool schemas matching `mcp.list_tools()`.
2. `GET /health` returns the liveness payload; `GET /healthz` still works (alias).
3. The self-heal script `--check`/`--heal` is idempotent and never spawns a
   competing daemon.
4. Existing surfaces unchanged: `/mcp`, `/files/{token}/blob/{rel}`,
   `/skills/{name}.zip`, the landing page `/`, and `webctl.sh` verbs all still work.
5. `mcp.json` instructions + README document the new endpoints; the fleet gap
   matrix row for patentmcp updates to fully-conformant once landed.
6. **Bare `GET /skills` returns 200 listing `patentworks` by bare name**, and the
   full `list → download by name` chain succeeds for every listed entry. A check
   that only asserts "some zip downloads" does NOT satisfy this — that is exactly
   the shape that stayed green through BR_20260730.
