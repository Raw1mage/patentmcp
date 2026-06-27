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

wait_healthy() {
    local timeout=60 elapsed=0 status
    while [ $elapsed -lt $timeout ]; do
        status="$(docker inspect "$CONTAINER" --format '{{.State.Health.Status}}' 2>/dev/null || echo missing)"
        [ "$status" = "healthy" ] && return 0
        sleep 2; elapsed=$((elapsed + 2))
    done
    printf 'webctl: timeout waiting for %s to become healthy\n' "$CONTAINER" >&2
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
        docker compose -p "$PROJECT" up -d --build --force-recreate
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
