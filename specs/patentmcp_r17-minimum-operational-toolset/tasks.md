# Tasks: patentmcp_r17-minimum-operational-toolset

## 1. A1 — Portable result retrieval (resources/read)

- [x] 1.1 Add `_resources.py`: resource URI ↔ token/rel mapping + list/read over the live token store (reuse `TokenStore.blob_path` / `list_files` / `_safe_target`)
- [x] 1.2 Register the resource face in `patents.py` (FastMCP `add_resource` / template `patent://{token}/{rel}`); fail-loud on unknown token/rel
- [x] 1.3 Unit test: `resources/read` exact-bytes + unknown→typed error + `resources/list` mirrors store (`tests/test_resources.py`)

## 2. A2 — Structured capability summary

- [x] 2.1 Add capability-summary builder (transport / file ingress-egress / WebDAV state / companion / conditional families; endpoints tagged container vs host-visible)
- [x] 2.2 Widen `patentmcp_init` return to `{doctrine, capabilities}`; keep `prompts/get` prose-only; doctrine byte-identical
- [x] 2.3 Unit test: init envelope shape, doctrine == prompts/get body, endpoint visibility, no container socket host-executable (`tests/test_init_capabilities.py`)

## 3. A3 — Typed asset preflight + content assertions

- [x] 3.1 Add `_delivery.py`: pure preflight (empty / out-of-namespace) + content-assertion checker (min_files / nonempty / contains_rel)
- [x] 3.2 Wire preflight + optional assertion kwargs into `cache_export`; `EXPORT_EMPTY` on empty tree; assertion mismatch → typed error
- [x] 3.3 Unit test: empty export refused, assertion pass/fail, backward-compat no-assertion path byte-identical (`tests/test_delivery_preflight.py`)

## 4. Convergence — tests + R17.6 eval + closeout

- [x] 4.1 Run full pytest suite green (no regression)
- [x] 4.2 R17.6 end-to-end eval: host file → ingress → token → transform → assertion-backed QA → resource/blob egress; once portable-floor (no WebDAV), once with WebDAV (`tests/test_r17_conformance.py`)
- [x] 4.3 `mcp.json` version bump + R17 signpost
- [x] 4.4 Update standard §12 matrix R17 column (opencode repo); sync `specs/architecture.md`; `event_record` closeout; move BR to `issues/closed/`
