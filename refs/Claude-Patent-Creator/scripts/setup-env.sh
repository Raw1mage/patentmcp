#!/bin/bash
# Setup environment for patent creator session

if [ -n "$CLAUDE_ENV_FILE" ]; then
  # Add patent creator to PATH if installed
  if command -v patent-creator &> /dev/null; then
    echo "# Patent Creator CLI available" >> "$CLAUDE_ENV_FILE"
  fi

  # Check for BigQuery credentials
  if [ -f "$HOME/.config/gcloud/application_default_credentials.json" ]; then
    echo "# BigQuery authenticated" >> "$CLAUDE_ENV_FILE"
  fi
fi

echo "Patent Creator session initialized"
exit 0
