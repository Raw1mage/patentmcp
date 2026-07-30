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

assert_no_project_drift() {
    # `container_name: patentmcp` (docker-compose.yml:19) pins the name GLOBALLY,
    # across every compose project. So a container of that name owned by a
    # DIFFERENT project makes up/--force-recreate die inside the daemon with
    # "Conflict. The container name /patentmcp is already in use by container
    # <hash>" -- a message that never mentions compose projects, and so reads as
    # a stale-container problem rather than the drift it actually is.
    #
    # Observed 2026-07-22..30 (BR_20260730): a `docker compose up` run WITHOUT
    # -p defaults the project to the directory name (`patentmcp`), while this
    # script always drives `patentmcp-${USER}`. From then on `restart` was dead:
    # image build succeeded, recreate always conflicted.
    #
    # Fail fast with the actual cause and the repair, instead of handing the
    # operator a daemon conflict that does not name it.
    local owner
    owner="$(docker inspect "$CONTAINER" \
        --format '{{index .Config.Labels "com.docker.compose.project"}}' 2>/dev/null || true)"
    [ -z "$owner" ] && return 0            # no such container: nothing to collide with
    [ "$owner" = "$PROJECT" ] && return 0  # ours
    cat >&2 <<EOF
webctl: compose project drift -- refusing to run

  container '$CONTAINER' is owned by project '$owner'
  this script drives project              '$PROJECT'

  'container_name: $CONTAINER' is global, so these two projects cannot both
  hold it. Any up/restart from here fails inside the daemon with a name
  conflict that does not name this cause.

  To adopt the running container into '$PROJECT':

    docker compose -p '$owner' down
    ./webctl.sh start

  That does NOT remove the abandoned project's volumes. Inspect before
  assuming they are disposable -- the sessions volume holds the token store:

    docker volume ls --filter name=patentmcp
EOF
    return 1
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
        assert_no_project_drift
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
        # Drift check BEFORE the slow build: a conflicting container makes the
        # recreate fail regardless, so spending the uv-sync minutes first only
        # delays the same error (BR_20260730 symptom: [1/3] passed, [2/3] died).
        assert_no_project_drift
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
