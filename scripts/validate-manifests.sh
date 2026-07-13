#!/usr/bin/env bash
# validate-manifests — fail-fast JSON validation for MCP manifests.
#
# Root-cause guard for the 2026-07-13 incident: mcp.json is a HAND-MAINTAINED
# manifest (there is no generator). Its `instructions` field is a long multi-line
# string that is easy to hand-edit into invalid JSON — an embedded raw newline
# (unescaped U+0000–U+001F) makes the whole file un-parseable, and opencode's
# gateway silently SKIPS the MCP connect on a manifest parse error (no tools
# surface, container looks healthy). See
# issues/issue_20260713_mcp_json_generation_unescaped_instructions.md
#
# This script parses every manifest with `jq` and, for mcp.json specifically,
# also asserts the streamable-http url has NO trailing slash on the /mcp path
# (FastMCP 307-redirects POST /mcp/, which breaks the MCP handshake).
#
#   exit 0  all manifests valid
#   exit 1  a manifest failed validation (message on stderr)
#   exit 2  jq not installed
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$HERE")"

if ! command -v jq >/dev/null 2>&1; then
    echo "validate-manifests: FATAL: jq is not installed (required)." >&2
    exit 2
fi

# Manifests to validate (relative to repo root). .mcp.json is the stdio client
# config; mcp.json is the app manifest the gateway reads.
MANIFESTS=(mcp.json .mcp.json)

fail=0
for rel in "${MANIFESTS[@]}"; do
    f="$REPO_DIR/$rel"
    [ -f "$f" ] || continue

    if ! err="$(jq empty "$f" 2>&1)"; then
        echo "validate-manifests: FAIL: $rel is not valid JSON" >&2
        echo "  $err" >&2
        echo "  hint: a multi-line string value (e.g. \"instructions\") likely contains a raw" >&2
        echo "        newline — escape control chars as \\n. Never hand-embed literal newlines" >&2
        echo "        inside a JSON string." >&2
        fail=1
        continue
    fi

    # mcp.json-specific: streamable-http /mcp path must have no trailing slash.
    if [ "$rel" = "mcp.json" ]; then
        url="$(jq -r '.url // empty' "$f")"
        if [ -n "$url" ] && printf '%s' "$url" | grep -qE ':/mcp/$'; then
            echo "validate-manifests: FAIL: mcp.json url ends with '/mcp/' (trailing slash)" >&2
            echo "  url: $url" >&2
            echo "  hint: FastMCP 307-redirects POST /mcp/ and MCP clients don't follow it on" >&2
            echo "        POST — use '/mcp' with no trailing slash." >&2
            fail=1
        fi
    fi

    [ "$fail" -eq 0 ] && echo "validate-manifests: OK: $rel"
done

if [ "$fail" -ne 0 ]; then
    echo "validate-manifests: one or more manifests failed. Aborting." >&2
    exit 1
fi
echo "validate-manifests: all manifests valid."
exit 0
