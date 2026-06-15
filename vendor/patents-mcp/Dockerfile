# patentmcp — MCP server for USPTO / Google Patents / GPSS / EPO patent data.
#
# Transport is MCP Streamable HTTP over a Unix domain socket (see _http_app.py);
# the same Starlette app also serves the human landing page, /healthz, the
# token-store blob download, and the patentworks skill zip.
#
# Build context is the REPO ROOT (PatentDrafter/) so the image can bake in both
# the server (vendor/patents-mcp) and the skill tree (skills/) the download
# route serves. Build from the compose file, or manually:
#
#   docker build -f vendor/patents-mcp/Dockerfile -t patentmcp:latest .
#
# Run (HTTP-over-UDS) — normal path is docker compose; see docker-compose.yml.
FROM python:3.13-slim AS base

# uv drives install + run exactly like the host (uv.lock pinned).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONIOENCODING=utf-8 \
    PYTHONUTF8=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

WORKDIR /app/server

# 1) Resolve deps first (cache-friendly): only the manifests invalidate this layer.
COPY vendor/patents-mcp/pyproject.toml vendor/patents-mcp/uv.lock* ./
RUN uv sync --no-install-project --frozen 2>/dev/null || uv sync --no-install-project

# 2) Server source.
COPY vendor/patents-mcp/ ./
RUN uv sync --frozen 2>/dev/null || uv sync

# 3) Skill tree the /skills/<name>.zip route serves (lives at repo root).
COPY skills/ /app/skills/

# The blob/download routes derive paths from this; set explicitly because the
# in-container layout differs from the repo's vendor/.. nesting.
ENV PATENTS_SKILLS_ROOT=/app/skills

ENTRYPOINT ["uv", "run", "patent-mcp-server"]
CMD ["--transport", "http", "--uds", "/run/patentmcp/patentmcp.sock"]
