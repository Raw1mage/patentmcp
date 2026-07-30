#!/usr/bin/env bash
# Shared compose-project identity + drift guard.
#
# Why this file exists (VANS re-verification of BR_20260730)
# ==========================================================
#
# `container_name: patentmcp` is GLOBAL across compose projects, so exactly one
# project may hold it. webctl.sh grew `assert_no_project_drift` to fail fast on
# that collision — but scripts/patentmcp-self-heal.sh computes the SAME
# `patentmcp-${USER}` project and drives `docker compose up` WITHOUT the guard.
#
# So `--heal` still hit the raw daemon error the guard exists to translate:
#
#   Conflict. The container name "/patentmcp" is already in use by container …
#
# — a message that never mentions compose projects, which is precisely why the
# original drift went undiagnosed for 8 days.
#
# Two callers needing one rule is the same shape as the F1 defect in
# _skill_shipping.py: list and download each had their own admission rules and
# drifted apart. The fix there was ONE gate both paths call. This is that fix,
# applied to the shell side — copying the guard into self-heal would have
# recreated the very defect being repaired.
#
# Callers must source this file; it defines PROJECT and CONTAINER, and exports
# nothing else. Socket/repo paths stay with each caller (they differ: webctl.sh
# is cwd-relative, self-heal derives from its own location).

# shellcheck shell=bash

PROJECT="patentmcp-${USER:-$(id -un)}"
CONTAINER="patentmcp"

assert_no_project_drift() {
    # `container_name: patentmcp` (docker-compose.yml:19) pins the name GLOBALLY,
    # across every compose project. So a container of that name owned by a
    # DIFFERENT project makes up/--force-recreate die inside the daemon with
    # "Conflict. The container name /patentmcp is already in use by container
    # <hash>" -- a message that never mentions compose projects, and so reads as
    # a stale-container problem rather than the drift it actually is.
    #
    # Observed 2026-07-22..30 (BR_20260730): a `docker compose up` run WITHOUT
    # -p defaults the project to the directory name (`patentmcp`), while these
    # scripts always drive `patentmcp-${USER}`. From then on `restart` was dead:
    # image build succeeded, recreate always conflicted.
    #
    # Fail fast with the actual cause and the repair, instead of handing the
    # operator a daemon conflict that does not name it.
    local owner caller
    caller="$(basename "${0:-patentmcp}")"
    owner="$(docker inspect "$CONTAINER" \
        --format '{{index .Config.Labels "com.docker.compose.project"}}' 2>/dev/null || true)"
    [ -z "$owner" ] && return 0            # no such container: nothing to collide with
    [ "$owner" = "$PROJECT" ] && return 0  # ours
    cat >&2 <<EOF
${caller}: compose project drift -- refusing to run

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
