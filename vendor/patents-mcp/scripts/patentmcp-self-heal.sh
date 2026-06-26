#!/usr/bin/env bash
# patentmcp self-heal — idempotent health probe + targeted recovery.
#
# Complements webctl.sh (R7.4). Probes the UDS socket the container binds; when
# unhealthy, recreates ONLY patentmcp's own per-user compose project. Never
# spawns a competing daemon — recovery always flows through docker compose with
# the exact `-p patentmcp-${USER}` project webctl.sh uses.
#
#   --check   exit 0 if healthy (socket present), non-zero otherwise. No mutation.
#   --heal    if unhealthy, `docker compose -p patentmcp-${USER} up -d` (idempotent).
#   --help    usage.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$HERE")"          # vendor/patents-mcp (where docker-compose.yml lives)

PROJECT="patentmcp-${USER:-$(id -un)}"
SOCKET_DIR="$REPO_DIR/.run"
SOCKET="$SOCKET_DIR/patentmcp.sock"
CONTAINER="patentmcp"

usage() {
    cat <<EOF
usage: $0 {--check|--heal|--help}

  --check   Probe health (UDS socket exists). Exit 0 healthy, 1 unhealthy. Read-only.
  --heal    Probe; if unhealthy, recreate only the ${PROJECT} compose project (idempotent).
  --help    Show this message.

Health signal: existence of the bound Unix socket at
  ${SOCKET}
(same readiness check as webctl.sh health). --heal never spawns a competing
daemon; it brings up patentmcp's own per-user compose project.
EOF
}

is_healthy() {
    [ -S "$SOCKET" ]
}

heal() {
    if ! command -v docker >/dev/null 2>&1; then
        printf 'patentmcp-self-heal: docker not found in PATH; cannot heal\n' >&2
        return 2
    fi
    [ -d "$SOCKET_DIR" ] || mkdir -p "$SOCKET_DIR"
    chmod 755 "$SOCKET_DIR" 2>/dev/null || true
    # Idempotent: `up -d` is a no-op when already running+healthy; recreates the
    # container when it is gone/stopped. Scoped to patentmcp's own project only.
    ( cd "$REPO_DIR" && docker compose -p "$PROJECT" up -d )
    # Give the socket a brief window to appear (container healthcheck cadence).
    local elapsed=0
    while [ $elapsed -lt 30 ]; do
        is_healthy && return 0
        sleep 2; elapsed=$((elapsed + 2))
    done
    printf 'patentmcp-self-heal: socket still absent after heal (%s)\n' "$SOCKET" >&2
    return 1
}

case "${1:---check}" in
    --check)
        if is_healthy; then
            printf 'patentmcp-self-heal: healthy (socket %s)\n' "$SOCKET"
            exit 0
        fi
        printf 'patentmcp-self-heal: UNHEALTHY (no socket at %s)\n' "$SOCKET" >&2
        exit 1
        ;;
    --heal)
        if is_healthy; then
            printf 'patentmcp-self-heal: already healthy; nothing to do\n'
            exit 0
        fi
        printf 'patentmcp-self-heal: unhealthy; recreating %s\n' "$PROJECT" >&2
        heal
        ;;
    --help|-h)
        usage
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac
