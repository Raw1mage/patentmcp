# Spec: patentmcp_r17-minimum-operational-toolset

## Purpose

patentmcp conforms to MCP integration standard R17 (minimum operational toolset
+ host mediation): every produced binary is retrievable on the protocol-native
portable floor (`resources/read`), `patentmcp_init` advertises a structured
capability summary that distinguishes container from host-visible endpoints, and
delivery-oriented operations refuse empty/unresolved artifacts with typed,
machine-checkable assertions.

## Requirements

### Requirement: Portable result retrieval

The system SHALL expose `resources/list` and `resources/read` such that every
binary produced into the token store is retrievable without any host-private
extension (no `/files/blob`, no WebDAV).

#### Scenario: Read a produced artifact over the portable floor

- **WHEN** a client that has produced a token-store artifact calls
  `resources/read` for that artifact's URI
- **THEN** the exact bytes are returned, and an unknown token/rel yields a typed
  resource error (never an empty read)

### Requirement: Structured capability summary

`patentmcp_init` SHALL return the prose doctrine plus a compact machine-readable
capability summary; each advertised endpoint SHALL carry a visibility class and
no container socket path SHALL be presented as host-executable.

#### Scenario: Init advertises endpoint visibility

- **WHEN** a client calls `patentmcp_init`
- **THEN** the result carries `doctrine` (byte-identical to `prompts/get
  patentmcp_init`) and `capabilities` whose endpoints are tagged
  `container` or `host-visible`

### Requirement: Typed asset preflight and content assertions

Delivery-oriented operations SHALL reject empty / unresolved / out-of-namespace
assets before landing, and a transport-valid but empty artifact SHALL NOT be
reported delivery-ready.

#### Scenario: Empty export is refused

- **WHEN** `cache_export` is called for a cache whose working tree has no
  deliverable files
- **THEN** it fails with a typed `EXPORT_EMPTY` error and nothing is landed

## Acceptance Checks

- [ ] `resources/read` returns exact bytes for a produced artifact; unknown URI → typed error
- [ ] `resources/list` mirrors the live token-store artifacts
- [ ] `patentmcp_init` returns `{doctrine, capabilities}`; doctrine byte-identical to prompts/get
- [ ] capability endpoints carry `visibility`; no container socket shown host-executable
- [ ] `cache_export` refuses empty tree (`EXPORT_EMPTY`); content assertions enforced when supplied
- [ ] full pytest suite green (no regression)
- [ ] R17.6 end-to-end eval passes once portable-floor, once with WebDAV
