#!/bin/bash
# Auto-format Python code after changes

FILE_PATH=$(echo "$1" | jq -r '.tool_input.file_path // empty' 2>/dev/null)

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# Only format Python files
if [[ "$FILE_PATH" == *.py ]]; then
  # Format with black if available
  if command -v black &> /dev/null; then
    black --line-length 100 "$FILE_PATH" 2>&1
  fi

  # Lint with ruff if available
  if command -v ruff &> /dev/null; then
    ruff check --line-length 100 "$FILE_PATH" 2>&1 || true
  fi
fi

exit 0
