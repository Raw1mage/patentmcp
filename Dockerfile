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
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-install-project --frozen 2>/dev/null || uv sync --no-install-project

# 2) Server source and config files.
COPY src/ ./src/
COPY pyproject.toml uv.lock* README.md LICENSE ./
RUN uv sync --frozen 2>/dev/null || uv sync

# 3) Skill tree the /skills/<name>.zip route serves (lives at repo root).
COPY skills/ /app/skills/

# The blob/download routes derive paths from this; set explicitly because the
# in-container layout differs from the repo's vendor/.. nesting.
ENV PATENTS_SKILLS_ROOT=/app/skills

ENTRYPOINT ["uv", "run", "patent-mcp-server"]
CMD ["--transport", "http", "--uds", "/run/patentmcp/patentmcp.sock"]
