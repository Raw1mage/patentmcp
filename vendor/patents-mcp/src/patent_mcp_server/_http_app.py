"""HTTP/UDS transport for patents-mcp (docxmcp-style).

Combines, in ONE Starlette ASGI app served over a Unix domain socket (preferred)
or TCP:

  * /mcp                          — MCP Streamable HTTP (FastMCP session manager)
  * /files/{token}/blob/{rel}     — token-store blob download (same as stdio mode)
  * /healthz                      — liveness + store stats
  * /                             — human-readable landing page (install guide +
                                    live tool list + skill download button)
  * /skills/patentworks.zip       — the patentworks skill packaged on the fly

The backend stays UDS-only in production; an opencode/opencms gateway fronts it
as ``https://<host>/patentmcp/...``. Because handles fall back to the relative
``/files/...`` path when no absolute base URL is set, downloads work unchanged
through that gateway prefix.
"""
from __future__ import annotations

import html
import io
import logging
import os
import zipfile
from pathlib import Path
from typing import Optional

_log = logging.getLogger("patents_mcp.http")

_SERVICE_MARKER = "patents-mcp-files"
_SKILL_NAME = "patentworks"


def _skills_root() -> Path:
    """Repo ``skills/`` dir. Override with PATENTS_SKILLS_ROOT; else derive from
    this file's location (…/vendor/patents-mcp/src/patent_mcp_server/_http_app.py
    → repo root is parents[4])."""
    env = os.environ.get("PATENTS_SKILLS_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[4] / "skills"


def _zip_skill(skill_dir: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(skill_dir.rglob("*")):
            if path.is_file():
                zf.write(path, arcname=str(path.relative_to(skill_dir.parent)))
    return buf.getvalue()


_LANDING_CSS = """
:root{--bg:#101418;--card:#19202a;--fg:#e6edf3;--muted:#9aa7b4;--accent:#4fc1ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.6 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;padding:2.2rem}
h1{margin:.2rem 0}h2{margin-top:1.8rem;border-bottom:1px solid #2a3441;padding-bottom:.3rem}
code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
pre{background:#0c1116;border:1px solid #243040;border-radius:8px;padding:1rem;overflow:auto}
code{color:var(--accent)}.muted{color:var(--muted)}
.card{background:var(--card);border:1px solid #243040;border-radius:10px;padding:1rem 1.2rem;margin:.6rem 0}
a.btn{display:inline-block;background:var(--accent);color:#06121c;font-weight:600;
text-decoration:none;padding:.6rem 1.1rem;border-radius:8px;margin-top:.4rem}
table{border-collapse:collapse;width:100%}td{border-top:1px solid #243040;padding:.4rem .6rem;vertical-align:top}
td.name{color:var(--accent);white-space:nowrap;font-family:ui-monospace,monospace}
.count{color:var(--muted);font-weight:400;font-size:.8em}
"""


def _landing_html(tools, prefix: str, skill_available: bool) -> str:
    rows = "".join(
        f"<tr><td class=name>{html.escape(t.name)}</td>"
        f"<td>{html.escape((t.description or '').strip().splitlines()[0] if (t.description or '').strip() else '')}</td></tr>"
        for t in tools
    )
    dl = (
        f'<a class=btn href="{prefix}/skills/{_SKILL_NAME}.zip">⬇ Download {_SKILL_NAME} skill (.zip)</a>'
        if skill_available
        else '<p class=muted>Skill package unavailable on this host.</p>'
    )
    stdio_cfg = html.escape(
        '{\n'
        '  "mcpServers": {\n'
        '    "patentmcp": {\n'
        '      "command": "uv",\n'
        '      "args": ["--directory", "/path/to/patents-mcp", "run", "patent-mcp-server"],\n'
        '      "env": { "GOOGLE_CLOUD_PROJECT": "...", "GOOGLE_APPLICATION_CREDENTIALS": "...",\n'
        '               "GPSS_USER_CODE": "...", "EPO_CONSUMER_KEY": "...", "EPO_CONSUMER_SECRET": "..." }\n'
        '    }\n'
        '  }\n'
        '}'
    )
    http_cfg = html.escape(
        '{\n'
        '  "patentmcp": {\n'
        '    "transport": "streamable-http",\n'
        f'    "url": "https://<gateway-host>{prefix}/mcp"\n'
        '  }\n'
        '}'
    )
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>patentmcp</title><style>{_LANDING_CSS}</style></head><body>
<h1>patentmcp</h1>
<p class=muted>USPTO / Google Patents / GPSS / EPO patent-data MCP server.
Streamable HTTP at <code>{prefix}/mcp</code>; this backend is UDS-only and fronted by the gateway.</p>

<h2>Install the skill</h2>
<div class=card>{dl}
<p class=muted>Unzip into your Claude/agent skills directory (e.g. <code>~/.claude/skills/</code>).
The <code>{_SKILL_NAME}</code> skill orchestrates disclosure → screening → drafting against this server's tools.</p></div>

<h2>Connect the MCP server</h2>
<p>Remote client (through the gateway) — Streamable HTTP:</p>
<pre>{http_cfg}</pre>
<p>Local client — stdio via <code>uv</code> (<code>.mcp.json</code>):</p>
<pre>{stdio_cfg}</pre>

<h2>Endpoints</h2>
<div class=card>
<p>MCP: <code>{prefix}/mcp</code></p>
<p>File download: <code>{prefix}/files/{{token}}/blob/{{rel}}</code></p>
<p>Health: <code>{prefix}/healthz</code></p>
<p>Skill: <code>{prefix}/skills/{_SKILL_NAME}.zip</code></p></div>

<h2>Tools <span class=count>({len(tools)})</span></h2>
<table>{rows}</table>
</body></html>"""


def build_app(mcp, store):
    """Return a Starlette app = FastMCP streamable-http (/mcp, with its session
    lifespan already wired) + file/landing/skill routes appended."""
    from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response
    from starlette.routing import Route
    from mcp.server.transport_security import TransportSecuritySettings

    # Behind a trusted UDS gateway the Host header is set by the proxy, so the
    # default DNS-rebinding guard would reject every request. Disable it (the
    # gateway is the trust boundary). Must be set before streamable_http_app().
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )

    # FastMCP builds the app with /mcp mounted and the session-manager lifespan.
    app = mcp.streamable_http_app()

    # Gateway path prefix used when rendering absolute-looking links on the page.
    prefix = os.environ.get("PATENTS_GATEWAY_PREFIX", "")

    async def blob(request):
        token = request.path_params["token"]
        rel = request.path_params["rel"]
        try:
            path = store.blob_path(token, rel)
        except Exception as e:  # noqa: BLE001
            return JSONResponse({"error": "not_found", "detail": str(e)}, status_code=404)
        return FileResponse(str(path), filename=path.name)

    async def health(request):
        return JSONResponse({"ok": True, "service": _SERVICE_MARKER, "store": store.stats()})

    async def skill_zip(request):
        skill_dir = _skills_root() / _SKILL_NAME
        if not skill_dir.is_dir():
            return JSONResponse({"error": "skill_not_found", "skill": _SKILL_NAME}, status_code=404)
        data = _zip_skill(skill_dir)
        return Response(
            content=data,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{_SKILL_NAME}.zip"'},
        )

    async def landing(request):
        try:
            tools = await mcp.list_tools()
        except Exception:  # noqa: BLE001
            tools = []
        skill_available = (_skills_root() / _SKILL_NAME).is_dir()
        return HTMLResponse(_landing_html(tools, prefix, skill_available))

    app.router.routes.extend([
        Route("/", landing, methods=["GET"]),
        Route("/healthz", health, methods=["GET"]),
        Route("/files/{token}/blob/{rel:path}", blob, methods=["GET"]),
        Route(f"/skills/{_SKILL_NAME}.zip", skill_zip, methods=["GET"]),
    ])
    return app


def serve(mcp, store, *, uds: Optional[str] = None,
          host: str = "127.0.0.1", port: int = 8078) -> None:
    """Blocking: run the combined app over UDS (preferred) or TCP."""
    import uvicorn
    from patent_mcp_server import _file_server

    app = build_app(mcp, store)
    if uds:
        # Relative /files paths flow through the gateway prefix; no absolute base.
        parent = os.path.dirname(uds)
        if parent:
            os.makedirs(parent, exist_ok=True)
        config = uvicorn.Config(app, uds=uds, log_level="info")
        _log.info("patentmcp http listening on unix:%s (/mcp, /files, /skills, /)", uds)
    else:
        _file_server.FILE_BASE_URL = f"http://{host}:{port}"
        config = uvicorn.Config(app, host=host, port=port, log_level="info")
        _log.info("patentmcp http listening on http://%s:%d (/mcp, /files, /skills, /)", host, port)
    # uvicorn.Server.run() is blocking and drives the session-manager lifespan.
    uvicorn.Server(config).run()
