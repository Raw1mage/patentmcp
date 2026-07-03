#!/usr/bin/env bash
# patentmcp container lifecycle wrapper (mirrors docxmcp/webctl.sh).
#
# Always uses `-p patentmcp-${USER}` so each user gets exactly ONE per-user
# compose project. The opencode gateway's /toggle endpoint invokes
# `start` / `stop`; /health checks socket existence.
#
# Subcommands:
#   start    bring up (idempotent; builds image if missing)
#   stop     stop without removing
#   restart  rebuild image + force-recreate + wait healthy
#   refresh  alias for restart
#   health   exit 0 if the UDS socket exists; non-zero otherwise
#   clean    bring down current project (preserves named volume)
#   purge    bring down + delete named volume (DESTRUCTIVE — drops token store)
set -euo pipefail

cd "$(dirname "$0")"

PROJECT="patentmcp-${USER:-$(id -un)}"
SOCKET_DIR="$(pwd)/.run"
SOCKET="$SOCKET_DIR/patentmcp.sock"
CONTAINER="patentmcp"

ensure_socket_dir() {
    [ -d "$SOCKET_DIR" ] || mkdir -p "$SOCKET_DIR"
    chmod 755 "$SOCKET_DIR" 2>/dev/null || true
}

resolve_container() {
    # Compose can leave a temp-named container (e.g. <hash>_patentmcp) when a
    # recreate is interrupted; resolve by project label, fall back to the
    # canonical name so health checks never go blind (BR_20260703).
    local cid
    cid="$(docker compose -p "$PROJECT" ps -q patentmcp 2>/dev/null | head -1)"
    printf '%s' "${cid:-$CONTAINER}"
}

wait_healthy() {
    local timeout=60 elapsed=0 status target
    target="$(resolve_container)"
    while [ $elapsed -lt $timeout ]; do
        status="$(docker inspect "$target" --format '{{.State.Health.Status}}' 2>/dev/null || echo missing)"
        [ "$status" = "healthy" ] && return 0
        sleep 2; elapsed=$((elapsed + 2))
    done
    printf 'webctl: timeout waiting for %s to become healthy (last status: %s)\n' "$target" "$status" >&2
    printf 'webctl: container state and recent logs follow\n' >&2
    docker ps -a --filter "label=com.docker.compose.project=$PROJECT" --format '{{.Names}} | {{.Status}}' >&2 || true
    docker logs --tail 20 "$target" >&2 2>&1 || true
    return 1
}

case "${1:-}" in
    start)
        ensure_socket_dir
        docker compose -p "$PROJECT" up -d
        wait_healthy
        ;;
    stop)
        docker compose -p "$PROJECT" stop
        ;;
    restart|refresh)
        ensure_socket_dir
        # Build FIRST as its own step: the image rebuild (uv sync + bytecode
        # compile) is the slow part; doing it inside `up --build` produced a
        # long silent window, and killing that window mid-recreate strands a
        # Created temp-named container (BR_20260703). Separate steps fail fast
        # per phase and keep the recreate window short.
        echo "webctl: [1/3] building image"
        docker compose -p "$PROJECT" build
        echo "webctl: [2/3] recreating container"
        docker compose -p "$PROJECT" up -d --force-recreate
        echo "webctl: [3/3] waiting for health"
        wait_healthy
        ;;
    health)
        [ -S "$SOCKET" ]
        ;;
    clean)
        docker compose -p "$PROJECT" down
        ;;
    purge)
        docker compose -p "$PROJECT" down -v
        ;;
    *)
        echo "usage: $0 {start|stop|restart|refresh|health|clean|purge}" >&2
        exit 2
        ;;
esac
