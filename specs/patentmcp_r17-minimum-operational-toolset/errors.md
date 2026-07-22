# Errors: patentmcp_r17-minimum-operational-toolset

## Error Catalogue

| Code | Condition | Surface | Recovery |
| ---- | --------- | ------- | -------- |
| `resource_not_found` | `resources/read` for an unknown token or missing rel | MCP resource error (SDK) | fix the URI; produce the artifact first |
| `resource_traversal` / `resource_not_found` | `resources/read` rel escapes the token namespace | MCP resource error | use a rel within the token namespace |
| `EXPORT_EMPTY` | `cache_export` on a working tree with zero deliverable files | typed `{success:false, error_code}` | write deliverables into the cache first (DAV PUT / produce), then export |
| `ASSERTION_FAILED` | supplied content assertion (min_files / nonempty / contains_rel) not met | typed `{success:false, error_code, detail}` | fix the deliverable set or relax the assertion |
| `EXPORT_TARGET_UNREACHABLE` | (existing) export target parent missing | typed error | create the parent reference point |
| `WORKSPACE_CLOSE_DIRTY` | (existing) cache_close with un-exported changes | typed error + `unlanded[]` | export first or force=True |
| `DOCTRINE_SOURCE_MISSING/EMPTY` | (existing) `_guide_doctrine()` source unreadable | RuntimeError fail-fast (天條 §11) | confirm Dockerfile COPY skills/ + PATENTS_SKILLS_ROOT |

All new error surfaces are fail-loud typed envelopes; none is a silent fallback (天條 §11). An empty transport-valid artifact is refused, never reported delivery-ready (R17.2.5).
