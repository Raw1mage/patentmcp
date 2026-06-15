---
description: Run complete setup for Claude Patent Creator (install dependencies, download MPEP, build index)
allowed-tools: Bash
---

# Setup Patent Creator

Complete installation and configuration of the Claude Patent Creator MCP server.

## Instructions

1. Verify we're in the project root (the directory containing `pyproject.toml`)
2. Run the patent-creator setup command
3. Monitor progress through:
   - PyTorch installation
   - MPEP PDF downloads (500MB)
   - Index building (5-15 min GPU, 35-65 min CPU)
   - BigQuery configuration
   - MCP server registration
4. Verify successful setup

## Command

```bash
# Replace with your plugin path or use CLAUDE_PLUGIN_ROOT
cd ${CLAUDE_PLUGIN_ROOT}
python install.py
```

Or if already installed:

```bash
patent-creator setup
```

## What This Does

- Detects OS and hardware (GPU/CPU)
- Installs PyTorch with correct CUDA version
- Downloads USPTO examination rules (MPEP, 35 USC, 37 CFR)
- Builds hybrid search index (FAISS + BM25)
- Configures BigQuery for patent search
- Registers MCP server with Claude Code

## Expected Output

- Installation confirmation
- Index build completion message
- MCP server registration success
- Health check passing
