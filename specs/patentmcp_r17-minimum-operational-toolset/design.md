# Design: patentmcp_r17-minimum-operational-toolset

## Context

patentmcp (v0.5.0) is a Python FastMCP service (`src/patent_mcp_server/`). Its
file-delivery floor is the docxmcp-style token store: every produced binary is
minted as `tok_*` under `<root>/<token>/<filename>` and served over the
**host-private** extensions — UDS/TCP `GET /files/{token}/blob/{rel}`
(`_http_app.py:668`) and the WebDAV `/dav/{subject}/{rel}` working-cache face.
There is **no** protocol-native `resources/read`, so a bare MCP client that only
speaks the wire protocol cannot retrieve a produced artifact — it must know the
host-private blob path. R17.1(c) makes `resources/read` a MUST: the portable
floor (R0/R2) has to work without host-private extensions.

Two smaller gaps ride alongside: `patentmcp_init` (`patents.py:4511`) returns
`_guide_doctrine()` **prose only** (R17.1.1 wants a compact machine-readable
capability summary that distinguishes container from host-visible endpoints),
and the delivery path (`cache_export`, `patents.py:5192`) has **no** typed asset
preflight / content assertions (R17.2.4/5 — an empty transport-valid artifact
must never be reported delivery-ready).

The three gaps are functionally independent (IDEF0 A1/A2/A3) and can be built in
parallel, converging only at the test + R17.6-eval gate.

## Goals / Non-Goals

**Goals**

- A1: protocol-native `resources/list` + `resources/read` over the token store,
  so every produced binary is reachable on the portable floor.
- A2: `patentmcp_init` returns prose doctrine **plus** a structured capability
  summary, endpoints classified container vs host-visible.
- A3: `cache_export` typed asset preflight + content assertions; empty artifact
  is fail-loud, never delivery-ready.
- Full pytest suite green + R17.6 end-to-end eval (portable floor + WebDAV).

**Non-Goals**

- No R17.3 host-side ingress mediation (Layer 2, not this repo).
- No removal of the `/files/blob` or `/dav` host extensions — R17 explicitly
  allows a host accelerator to coexist with the portable floor.
- No behavioural change to search/fetch/bulk tools or the token-store on-disk
  layout / docxmcp compatibility contract.

## Decisions

- **DD-1: `resources/read` is served by a FastMCP dynamic resource over the live
  token store, URI `patent://{token}/{rel}`.** The SDK exposes
  `FastMCP.add_resource` + a `resources/read` handler; a `ResourceTemplate`
  (`patent://{token}/{rel}`) maps a read to `TokenStore.blob_path(token, rel)`,
  which already resolves + traversal-checks the path (`_token_store.py:278`,
  reusing `_safe_target`). `resources/list` enumerates the live token store
  (every entry's `list_files()` rels → one resource URI each), so the resource
  set always mirrors what has actually been produced — single source, zero
  drift with `/files/blob`. Unknown token/rel → the SDK's typed resource error
  (fail-loud, never an empty read). *Alternatives rejected:* (a) a static
  per-artifact `@mcp.resource` — impossible, artifacts are minted at runtime;
  (b) exposing on-disk absolute paths as `file://` resources — leaks host paths
  into the protocol (violates R17.1.1 spirit + traversal safety).
- **DD-2: `patentmcp_init` return type widens from `str` to a structured
  envelope `{doctrine, capabilities}`; the `prompts/get` face stays prose-only.**
  The tool face can return structured content; `prompts/get` semantically
  returns a prompt *message* (text), so it keeps projecting `_guide_doctrine()`
  verbatim. R15.5 no-drift is preserved because the **doctrine** field is still
  the exact `_guide_doctrine()` string, byte-identical to the prompt face — the
  capabilities are additive metadata, not doctrine. A test asserts
  `init()["doctrine"] == prompts/get body`. *Alternative rejected:* stuffing
  capabilities into the prose — would break byte-identity and bloat the guide.
- **DD-3: capability endpoints carry an explicit `visibility` tag
  (`container` | `host-visible`) and never present a container socket as
  host-executable.** The UDS socket path is `container`-visibility (reachable
  only via the gateway); the gateway-fronted `https://…/patentmcp/mcp`,
  `/files/.../blob`, `/dav` are `host-visible`. The summary states the transport
  facts without emitting a `uv run …` or `curl --unix-socket <container-path>`
  recipe that a host could not execute (R17.1.1 + R17.6 scenario 2).
- **DD-4: `cache_export` gains a typed asset preflight + optional content
  assertions; an empty working tree is refused with `EXPORT_EMPTY`.** Before the
  COPY, preflight rejects: zero deliverable files (`EXPORT_EMPTY`), and (when
  assertions are supplied) a mismatch of `assert_min_files` / `assert_nonempty`
  / `assert_contains_rel`. A transport-valid but empty cache is **not**
  delivery-ready (R17.2.5). Assertions are opt-in kwargs so existing callers are
  byte-identical (天條 §11 — no silent new required fields). *Alternative
  rejected:* a separate `cache_assert` tool — splits the delivery gate from the
  delivery act, letting an un-asserted empty export still land.
- **DD-5: assertions/preflight live in a small pure helper (`_delivery.py`) so
  they are unit-testable without the MCP/network stack** and reusable by any
  future delivery-oriented tool (e.g. `gpss4_advanced_search` cache delivery).

## Risks / Trade-offs

- **SDK resource API shape may differ across `mcp` versions** — mitigation:
  probed the installed SDK (`FastMCP.add_resource` / `read_resource` /
  `ResourceTemplate` present); implement against the concrete installed API and
  cover with a unit test that calls the read handler directly.
- **`resources/list` over a large token store could be heavy** — mitigation:
  the store is bounded (TTL reap + size cap); list is cold-path (client
  discovery), not a hot loop. Acceptable.
- **Widening `patentmcp_init` return type** could surprise a caller that expects
  a bare string — mitigation: the tool is `init`/discovery, called once; the
  structured envelope is the R17-conformant shape and the doctrine remains
  fully present under `.doctrine`.

## Critical Files

- `src/patent_mcp_server/patents.py` — `patentmcp_init` (:4511), `cache_export`
  (:5192), and the new `@mcp.resource` / `add_resource` registration site.
- `src/patent_mcp_server/_token_store.py` — `blob_path` / `list_files` /
  `_safe_target` reused by the resource read + list handlers.
- `src/patent_mcp_server/_resources.py` — NEW: resource URI ↔ token/rel mapping +
  list/read logic (SSOT).
- `src/patent_mcp_server/_delivery.py` — NEW: pure preflight + content-assertion
  checker (DD-5).
- `src/patent_mcp_server/_http_app.py` — unchanged blob face (coexists as host
  accelerator); complements the new portable resource floor.
- `mcp.json` — version bump + R17 signpost.
- `tests/` — resource face, capability summary, preflight/assertions, R17.6 eval.
