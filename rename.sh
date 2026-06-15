#!/usr/bin/env bash
# One-shot repo rename: PatentDrafter -> patentworks.
# Run this AFTER closing the folder in your IDE (it moves the dir, rewrites
# .mcp.json absolute paths, and relocates the Claude memory dir to match the
# new project key). Then reopen /home/pkcs12/projects/patentworks.
set -euo pipefail

OLD=/home/pkcs12/projects/PatentDrafter
NEW=/home/pkcs12/projects/patentworks
MEM_OLD=/home/pkcs12/.claude/projects/-home-pkcs12-projects-PatentDrafter
MEM_NEW=/home/pkcs12/.claude/projects/-home-pkcs12-projects-patentworks

[ -d "$OLD" ] || { echo "source repo not found: $OLD (already renamed?)"; exit 1; }
[ -e "$NEW" ] && { echo "target already exists: $NEW"; exit 1; }

echo "1) repo dir: $OLD -> $NEW"
mv "$OLD" "$NEW"

echo "2) rewrite absolute paths in .mcp.json"
sed -i 's#/projects/PatentDrafter/#/projects/patentworks/#g' "$NEW/.mcp.json"

echo "3) relocate Claude memory dir to match new project key"
if [ -d "$MEM_OLD" ] && [ ! -e "$MEM_NEW" ]; then
  mv "$MEM_OLD" "$MEM_NEW"
else
  echo "   (skipped: memory dir already moved or missing)"
fi

echo "done. Reopen $NEW in your IDE; MCP reloads as 'patentmcp'."
