# Errors: patentmcp_mcp-standard-conformance

## Error Catalogue

| Code                      | Trigger                                              | User-visible message                           | Recovery                                                                                   | Layer                               |
| ------------------------- | ---------------------------------------------------- | ---------------------------------------------- | ------------------------------------------------------------------------------------------ | ----------------------------------- |
| `TOOLS_REGISTRY_ERROR`    | `mcp.list_tools()` raises while serving `GET /tools` | `500 {"error":"tool registry unavailable"}`    | Fail loud — caller retries; NEVER return silent `{tools:[]}` (user 天條)                   | `_http_app.py` /tools route         |
| `TOOLS_SERIALIZE_ERROR`   | A Tool object has non-JSON-native fields             | `500 {"error":"tool schema not serializable"}` | DD-4 projection to `{name,description,inputSchema}` should prevent; if hit, fix projection | /tools route                        |
| `HEALTH_STORE_ERROR`      | `store.stats()` raises during `GET /health`          | `500 {"error":"store unavailable"}`            | Surfaces real store fault; do not mask as ok                                               | /health + /healthz shared coroutine |
| `SELFHEAL_DOCKER_MISSING` | `docker` not on PATH during self-heal                | stderr `docker not found`, exit non-zero       | `command -v docker` precheck guard bails early                                             | self-heal script                    |
| `SELFHEAL_WRONG_PROJECT`  | Compose project name mismatch                        | (guarded) only `patentmcp-${USER}` recreated   | DD-5 pins exact project name                                                               | self-heal script                    |

## Non-errors (by design)

- `GET /healthz` continuing to work is REQUIRED, not deprecated — alias retained for back-compat.
- Self-heal `--check` on a healthy service returns exit 0 with `action: none` (idempotent, not an error).
