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
import time
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


# UI strings per locale. Tool descriptions come from the MCP server (English
# docstrings) and are not translated; only the page chrome is localized.
STRINGS = {
    "en": {
        "subtitle": "USPTO / Google Patents / GPSS / EPO patent-data MCP server. "
                    "Streamable HTTP at <code>{mcp}</code>; this backend is UDS-only and fronted by the gateway.",
        "install_h2": "Install the skill",
        "install_btn": "⬇ Download {skill} skill (.zip)",
        "install_note": "Unzip into your Claude/agent skills directory (e.g. <code>~/.claude/skills/</code>). "
                        "The <code>{skill}</code> skill orchestrates disclosure → screening → drafting against this server's tools.",
        "skill_unavailable": "Skill package unavailable on this host.",
        "connect_h2": "Connect the MCP server",
        "connect_remote": "Remote client (through the gateway) — Streamable HTTP:",
        "connect_local": "Local client — stdio via <code>uv</code> (<code>.mcp.json</code>):",
        "handshake_h2": "Tools not showing up? Connection checklist",
        "handshake_note": "If patentmcp is configured but its tools never appear in your session (tool search returns nothing), your client isn't completing the Streamable-HTTP handshake. Verify:",
        "handshake_steps": [
            "Endpoint is the full gateway-prefixed URL: <code>{mcp}</code> (a bare host without the mount prefix hits the SPA, not the MCP server).",
            "Request header <code>Accept: application/json, text/event-stream</code> is sent (Streamable HTTP requires both).",
            "You POST <code>initialize</code> FIRST, then read <code>mcp-session-id</code> from the response headers.",
            "Every later request (<code>notifications/initialized</code>, <code>tools/list</code>, <code>tools/call</code>) carries that <code>mcp-session-id</code> + <code>MCP-Protocol-Version</code>.",
            "Responses are SSE (<code>event: message</code> + <code>data: {{...}}</code>) — parse the <code>data:</code> lines.",
        ],
        "handshake_gotcha": "POSTing tools/list before initialize returns <code>-32600 Missing session ID</code> — that error means the handshake order is wrong, not that the server is down.",
        "endpoints_h2": "Endpoints",
        "ep_mcp": "MCP", "ep_file": "File download", "ep_health": "Health", "ep_skill": "Skill",
        "tools_h2": "Tools",
    },
    "zh-Hant": {
        "subtitle": "USPTO / Google Patents / GPSS / EPO 專利資料 MCP 伺服器。"
                    "Streamable HTTP 端點在 <code>{mcp}</code>；後端僅走 UDS，由 gateway 對外代理。",
        "install_h2": "安裝 skill",
        "install_btn": "⬇ 下載 {skill} skill（.zip）",
        "install_note": "解壓到你的 Claude/agent skills 目錄（例如 <code>~/.claude/skills/</code>）。"
                        "<code>{skill}</code> skill 串起 交底書 → 前案檢索 → 起草，呼叫本伺服器的工具。",
        "skill_unavailable": "本主機未提供 skill 套件。",
        "connect_h2": "連接 MCP 伺服器",
        "connect_remote": "遠端 client（經 gateway）— Streamable HTTP：",
        "connect_local": "本機 client — 經 <code>uv</code> 的 stdio（<code>.mcp.json</code>）：",
        "handshake_h2": "工具沒出現？連線檢查清單",
        "handshake_note": "若已設定 patentmcp 但工具始終沒出現在 session（工具搜尋查無），代表你的 client 沒完成 Streamable-HTTP 握手。逐項確認：",
        "handshake_steps": [
            "端點用完整含 gateway 前綴的 URL：<code>{mcp}</code>（少了掛載前綴的裸 host 會打到 SPA，不是 MCP 伺服器）。",
            "請求帶 header <code>Accept: application/json, text/event-stream</code>（Streamable HTTP 兩者都要）。",
            "先 POST <code>initialize</code>，再從回應 header 取 <code>mcp-session-id</code>。",
            "之後每個請求（<code>notifications/initialized</code>、<code>tools/list</code>、<code>tools/call</code>）都帶上該 <code>mcp-session-id</code> + <code>MCP-Protocol-Version</code>。",
            "回應是 SSE（<code>event: message</code> + <code>data: {{...}}</code>）——需自行解析 <code>data:</code> 行。",
        ],
        "handshake_gotcha": "未先 initialize 就 POST tools/list 會得到 <code>-32600 Missing session ID</code>——這代表握手順序錯，不是伺服器故障。",
        "endpoints_h2": "端點",
        "ep_mcp": "MCP", "ep_file": "檔案下載", "ep_health": "健康檢查", "ep_skill": "Skill",
        "tools_h2": "工具",
    },
    "zh-Hans": {
        "subtitle": "USPTO / Google Patents / GPSS / EPO 专利数据 MCP 服务器。"
                    "Streamable HTTP 端点在 <code>{mcp}</code>；后端仅走 UDS，由 gateway 对外代理。",
        "install_h2": "安装 skill",
        "install_btn": "⬇ 下载 {skill} skill（.zip）",
        "install_note": "解压到你的 Claude/agent skills 目录（例如 <code>~/.claude/skills/</code>）。"
                        "<code>{skill}</code> skill 串起 交底书 → 在先技术检索 → 起草，调用本服务器的工具。",
        "skill_unavailable": "本主机未提供 skill 套件。",
        "connect_h2": "连接 MCP 服务器",
        "connect_remote": "远端 client（经 gateway）— Streamable HTTP：",
        "connect_local": "本机 client — 经 <code>uv</code> 的 stdio（<code>.mcp.json</code>）：",
        "handshake_h2": "工具没出现？连线检查清单",
        "handshake_note": "若已配置 patentmcp 但工具始终没出现在 session（工具搜索查无），代表你的 client 没完成 Streamable-HTTP 握手。逐项确认：",
        "handshake_steps": [
            "端点用完整含 gateway 前缀的 URL：<code>{mcp}</code>（少了挂载前缀的裸 host 会打到 SPA，不是 MCP 服务器）。",
            "请求带 header <code>Accept: application/json, text/event-stream</code>（Streamable HTTP 两者都要）。",
            "先 POST <code>initialize</code>，再从响应 header 取 <code>mcp-session-id</code>。",
            "之后每个请求（<code>notifications/initialized</code>、<code>tools/list</code>、<code>tools/call</code>）都带上该 <code>mcp-session-id</code> + <code>MCP-Protocol-Version</code>。",
            "响应是 SSE（<code>event: message</code> + <code>data: {{...}}</code>）——需自行解析 <code>data:</code> 行。",
        ],
        "handshake_gotcha": "未先 initialize 就 POST tools/list 会得到 <code>-32600 Missing session ID</code>——这代表握手顺序错，不是服务器故障。",
        "endpoints_h2": "端点",
        "ep_mcp": "MCP", "ep_file": "文件下载", "ep_health": "健康检查", "ep_skill": "Skill",
        "tools_h2": "工具",
    },
}

_LOCALES = ("en", "zh-Hant", "zh-Hans")
_LOCALE_LABELS = {"en": "EN", "zh-Hant": "繁中", "zh-Hans": "简中"}


def _map_tag(tag: str):
    """Map one BCP-47 tag to a supported locale, or None. Bare `zh` → Traditional."""
    t = tag.strip().lower()
    if t.startswith("en"):
        return "en"
    if t.startswith("zh"):
        if "hant" in t or t in ("zh-tw", "zh-hk", "zh-mo"):
            return "zh-Hant"
        if "hans" in t or t in ("zh-cn", "zh-sg", "zh-my"):
            return "zh-Hans"
        return "zh-Hant"
    return None


def _pick_locale(lang_q, cookie_lang, accept_language) -> str:
    """Precedence: ?lang= → `pmlang` cookie → Accept-Language → en.

    The cookie path matters behind a protected gateway: `?lang=` adds a query
    so the URL is no longer the public landing and triggers login, but the
    cookie lets the switcher reload the bare (public) landing and still change
    language for anonymous visitors."""
    for src in (lang_q, cookie_lang):
        if src:
            if src in STRINGS:
                return src
            m = _map_tag(src)
            if m:
                return m
    for part in (accept_language or "").split(","):
        m = _map_tag(part.split(";")[0])
        if m:
            return m
    return "en"


def _landing_html(tools, prefix: str, skill_available: bool, locale: str = "en") -> str:
    s = STRINGS.get(locale, STRINGS["en"])
    mcp_ep = f"{prefix}/mcp"
    rows = "".join(
        f"<tr><td class=name><a href=\"{prefix}/tools/{html.escape(t.name)}\">{html.escape(t.name)}</a></td>"
        f"<td>{html.escape((t.description or '').strip().splitlines()[0] if (t.description or '').strip() else '')}</td></tr>"
        for t in tools
    )
    dl = (
        f'<a class=btn href="{prefix}/skills/{_SKILL_NAME}.zip">'
        + html.escape(s["install_btn"].format(skill=_SKILL_NAME)) + "</a>"
        if skill_available
        else f'<p class=muted>{html.escape(s["skill_unavailable"])}</p>'
    )
    # Switcher sets a cookie and reloads the BARE landing path (no query) so it
    # works even for anonymous visitors behind a protected gateway, where a
    # `?lang=` URL would be redirected to login.
    switch = " · ".join(
        (f'<strong>{_LOCALE_LABELS[loc]}</strong>' if loc == locale
         else f'<a href="?lang={loc}" '
              f"onclick=\"document.cookie='pmlang={loc};path=/;max-age=31536000';"
              f'location.href=location.pathname;return false">{_LOCALE_LABELS[loc]}</a>')
        for loc in _LOCALES
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
    return f"""<!doctype html><html lang="{locale}"><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>patentmcp</title><style>{_LANDING_CSS}</style></head><body>
<p class=muted style="float:right">{switch}</p>
<h1>patentmcp</h1>
<p class=muted>{s["subtitle"].format(mcp=mcp_ep)}</p>

<h2>{html.escape(s["install_h2"])}</h2>
<div class=card>{dl}
<p class=muted>{s["install_note"].format(skill=_SKILL_NAME)}</p></div>

<h2>{html.escape(s["connect_h2"])}</h2>
<p>{s["connect_remote"]}</p>
<pre>{http_cfg}</pre>
<p>{s["connect_local"]}</p>
<pre>{stdio_cfg}</pre>

<h2>{html.escape(s["handshake_h2"])}</h2>
<div class=card>
<p class=muted>{s["handshake_note"]}</p>
<ol>{"".join(f"<li>{step.format(mcp=mcp_ep)}</li>" for step in s["handshake_steps"])}</ol>
<p class=muted>{s["handshake_gotcha"]}</p></div>

<h2>{html.escape(s["endpoints_h2"])}</h2>
<div class=card>
<p>{html.escape(s["ep_mcp"])}: <code>{prefix}/mcp</code></p>
<p>{html.escape(s["ep_file"])}: <code>{prefix}/files/{{token}}/blob/{{rel}}</code></p>
<p>{html.escape(s["ep_health"])}: <code>{prefix}/healthz</code></p>
<p>{html.escape(s["ep_skill"])}: <code>{prefix}/skills/{_SKILL_NAME}.zip</code></p></div>

<h2>{html.escape(s["tools_h2"])} <span class=count>({len(tools)})</span></h2>
<table>{rows}</table>
</body></html>"""


def build_app(mcp, store):
    """Return a Starlette app = FastMCP streamable-http (/mcp, with its session
    lifespan already wired) + file/landing/skill + WebDAV cache routes appended.

    The DAV routes share this ONE app (no second lifespan — see serve() docstring
    on the single FastMCP session-manager lifespan constraint)."""
    from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response
    from starlette.routing import Route, Mount
    from mcp.server.transport_security import TransportSecuritySettings

    from patent_mcp_server._auth_provider import AuthProvider, AuthError, Identity
    from patent_mcp_server import _dav

    # WebDAV working-cache face (DD-4/DD-6). One auth provider + one process-local
    # lock table shared across all DAV requests on this app.
    _auth = AuthProvider(store)
    _locks = _dav.LockTable()
    _dav_handler = _dav.DavHandler(store, _locks)
    _DAV_MOUNT_PREFIX = "/dav"

    # Behind a trusted UDS gateway the Host header is set by the proxy, so the
    # default DNS-rebinding guard would reject every request. Disable it (the
    # gateway is the trust boundary). Must be set before streamable_http_app().
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )

    # FastMCP builds the app with /mcp mounted and the session-manager lifespan.
    app = mcp.streamable_http_app()

    # --- unified access log (plan observability_tool-friction-log, DD-6/DD-7) ---
    # W3C-semantics HTTP access log as a pure-ASGI middleware wrapping the whole
    # app. Every inbound HTTP request lands one category='access' row in the same
    # observability store as friction events (unified log mechanism). Pure ASGI
    # (not BaseHTTPMiddleware) so SSE / streaming responses are untouched: we only
    # peek the response-start status, never buffer the body. Fail-open — the
    # recorder swallows its own errors, so logging never breaks a request.
    from patent_mcp_server import friction_log as _obs

    def _access_log_mw(inner_app):
        async def middleware(scope, receive, send):
            if scope.get("type") != "http":
                # lifespan / websocket — pass through untouched.
                await inner_app(scope, receive, send)
                return
            start = time.monotonic()
            status_holder = {"code": None}

            async def send_wrapper(message):
                if message.get("type") == "http.response.start":
                    status_holder["code"] = message.get("status")
                await send(message)

            try:
                await inner_app(scope, receive, send_wrapper)
            finally:
                try:
                    headers = {
                        k.decode("latin-1").lower(): v.decode("latin-1")
                        for k, v in scope.get("headers", []) or []
                    }
                    client = scope.get("client") or None
                    client_ip = client[0] if client else None
                    ua = headers.get("user-agent")
                    raw_path = scope.get("raw_path")
                    uri = (
                        raw_path.decode("latin-1") if raw_path
                        else scope.get("path", "")
                    )
                    _obs.record_access(
                        method=scope.get("method"),
                        uri=uri,  # cs-uri-stem; query string intentionally dropped (DD-5)
                        status=status_holder["code"],
                        duration_ms=int((time.monotonic() - start) * 1000),
                        client_ip=client_ip,
                        user_agent=ua,
                        mcp_client=(ua.split("/")[0] if ua else None),
                    )
                except Exception:  # noqa: BLE001 — fail-open; logging never breaks a request
                    pass

        return middleware

    # NOTE: the middleware is applied at the END of build_app (after all routes
    # are attached via app.router.routes.extend below) — wrapping here would
    # replace the Starlette app with a bare ASGI callable that has no .router.

    # Gateway path prefix used when rendering absolute-looking links on the page.
    prefix = os.environ.get("PATENTS_GATEWAY_PREFIX", "")

    # --- SSE transport (legacy HTTP+SSE face) -------------------------------
    # DD-5: mcp.sse_app() ships its OWN lifespan + its own SseServerTransport;
    # mounting that whole Starlette app here would double-enter the app lifespan
    # (the streamable session-manager lifespan must run EXACTLY once — see
    # serve() docstring). So we DO NOT mount sse_app(); instead we build a bare
    # SseServerTransport and hand-wire its two endpoints (SSE stream GET +
    # message POST) as plain routes on THIS app. The transport needs no
    # app-lifespan of its own — each connection independently opens
    # connect_sse() and runs the low-level MCP server.
    #
    # The message POST path is advertised to the client inside the SSE stream as
    # an absolute URL; behind the gateway the client actually reaches
    # `{prefix}/sse/messages`, so the transport's endpoint MUST carry the gateway
    # prefix (same reasoning as the DAV base_href derivation, DD-4). When no
    # prefix is set (direct UDS/localhost) it degrades to the bare `/sse/messages`.
    from mcp.server.sse import SseServerTransport
    _sse_message_path = f"{prefix}/sse/messages"
    _sse = SseServerTransport(_sse_message_path)

    # SSE stream handler, mirroring the SDK's own handle_sse in sse_app()
    # (connect_sse drives the response over raw ASGI scope/receive/send). We
    # expose it as a Starlette Route endpoint (NOT a Mount) so the exact `/sse`
    # path matches without Mount's trailing-slash 307 redirect (which breaks SSE
    # clients that don't follow redirects). Inside, we reach the raw ASGI
    # send via request._send — the documented way to hand a Starlette request
    # back to a low-level ASGI response driver.
    from starlette.responses import Response as _SseAck

    async def sse_stream(request):
        async with _sse.connect_sse(
            request.scope, request.receive, request._send,
        ) as (read_stream, write_stream):
            await mcp._mcp_server.run(
                read_stream,
                write_stream,
                mcp._mcp_server.create_initialization_options(),
            )
        return _SseAck(status_code=204)

    def _schema_rows(schema, depth=0):
        """Render a JSON-Schema object's properties as HTML table rows.
        Recurses one level into nested object/array item schemas."""
        if not isinstance(schema, dict):
            return ""
        props = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        rows = []
        for name, spec in props.items():
            spec = spec if isinstance(spec, dict) else {}
            typ = spec.get("type")
            if isinstance(typ, list):
                typ = " | ".join(str(t) for t in typ)
            typ = typ or ("enum" if "enum" in spec else ("object" if "properties" in spec else ""))
            enum = spec.get("enum")
            default = spec.get("default")
            desc = (spec.get("description") or "").strip()
            req = "✔" if name in required else ""
            extra = []
            if enum is not None:
                extra.append("enum: " + ", ".join(html.escape(str(e)) for e in enum))
            if default is not None:
                extra.append("default: " + html.escape(str(default)))
            extra_html = ("<br><span class=muted>" + " · ".join(extra) + "</span>") if extra else ""
            pad = "padding-left:%drem" % (depth * 1.2 + 0.6)
            rows.append(
                f"<tr><td class=name style='{pad}'>{html.escape(str(name))}</td>"
                f"<td>{html.escape(str(typ))}</td>"
                f"<td style='text-align:center'>{req}</td>"
                f"<td>{html.escape(desc)}{extra_html}</td></tr>"
            )
            # Recurse one level into nested object / array-of-object.
            nested = None
            if isinstance(spec.get("properties"), dict):
                nested = spec
            elif isinstance(spec.get("items"), dict) and spec["items"].get("properties"):
                nested = spec["items"]
            if nested is not None and depth < 2:
                rows.append(_schema_rows(nested, depth + 1))
        return "".join(rows)

    def _tool_page_html(tool) -> str:
        name = html.escape(tool.name)
        desc = html.escape((tool.description or "").strip())
        schema = getattr(tool, "inputSchema", None) or {}
        import json as _json
        rows = _schema_rows(schema)
        table = (
            "<table><tr><th>參數</th><th>型別</th><th>必填</th><th>說明</th></tr>"
            + rows + "</table>"
            if rows else "<p class=muted>此工具無輸入參數。</p>"
        )
        raw = html.escape(_json.dumps(schema, ensure_ascii=False, indent=2))
        back = f'{prefix}/tools'
        return f"""<!doctype html><html lang=zh-Hant><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>{name} — patentmcp</title><style>{_LANDING_CSS}
th{{text-align:left;border-top:1px solid #243040;padding:.4rem .6rem;color:var(--muted);font-weight:600}}
</style></head><body>
<p class=muted><a href="{prefix}/">← patentmcp</a> · <a href="{back}">所有工具</a></p>
<h1><code>{name}</code></h1>
<p class=muted>{desc}</p>
<h2>輸入參數（inputSchema）</h2>
{table}
<h2>原始 JSON Schema</h2>
<pre>{raw}</pre>
</body></html>"""

    async def tool_page(request):
        want = request.path_params["name"]
        try:
            tools = await mcp.list_tools()
        except Exception as e:  # noqa: BLE001
            return JSONResponse(
                {"error": "tool_registry_unavailable", "detail": str(e)},
                status_code=500,
            )
        match = next((t for t in tools if t.name == want), None)
        if match is None:
            return HTMLResponse(
                f"<!doctype html><meta charset=utf-8><title>404</title>"
                f"<p>Unknown tool: <code>{html.escape(want)}</code>. "
                f"<a href='{prefix}/tools'>See all tools</a>.</p>",
                status_code=404,
            )
        return HTMLResponse(_tool_page_html(match))

    async def tools_index(request):
        try:
            tools = await mcp.list_tools()
        except Exception:  # noqa: BLE001
            tools = []
        rows = "".join(
            f"<tr><td class=name><a href=\"{prefix}/tools/{html.escape(t.name)}\">{html.escape(t.name)}</a></td>"
            f"<td>{html.escape((t.description or '').strip().splitlines()[0] if (t.description or '').strip() else '')}</td></tr>"
            for t in tools
        )
        return HTMLResponse(
            f"""<!doctype html><html lang=zh-Hant><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Tools — patentmcp</title><style>{_LANDING_CSS}</style></head><body>
<p class=muted><a href="{prefix}/">← patentmcp</a></p>
<h1>工具總覽 <span class=count>({len(tools)})</span></h1>
<p class=muted>點入任一工具查看完整 inputSchema。</p>
<table>{rows}</table>
</body></html>"""
        )

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

    async def tools_json(request):
        # Machine-readable tool introspection (standard R8.1). Sourced from the
        # SAME live registry the landing page reads — single source, zero drift.
        # Fail loud (500 JSON) on registry error; never a silent [] fallback.
        try:
            tools = await mcp.list_tools()
        except Exception as e:  # noqa: BLE001
            return JSONResponse(
                {"error": "tool_registry_unavailable", "detail": str(e)},
                status_code=500,
            )
        projected = [
            {
                "name": t.name,
                "description": t.description or "",
                "inputSchema": getattr(t, "inputSchema", None),
            }
            for t in tools
        ]
        return JSONResponse({"tools": projected})

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
        locale = _pick_locale(
            request.query_params.get("lang"),
            request.cookies.get("pmlang"),
            request.headers.get("accept-language"),
        )
        return HTMLResponse(
            _landing_html(tools, prefix, skill_available, locale),
            headers={"Content-Language": locale, "Vary": "Accept-Language"},
        )

    def _dav_error(status, code, detail, *, www_authenticate=False):
        hdrs = {}
        if www_authenticate:
            hdrs["WWW-Authenticate"] = 'Basic realm="patentmcp-webdav"'
        body = (f'<?xml version="1.0" encoding="utf-8"?>'
                f'<error xmlns="patentmcp"><code>{html.escape(code)}</code>'
                f'<detail>{html.escape(detail)}</detail></error>')
        return Response(body, status_code=status, media_type='application/xml',
                        headers=hdrs)

    async def dav(request):
        subject = request.path_params["subject"]
        rel = request.path_params.get("rel", "") or ""
        method = request.method

        # 1. Resolve subject -> token WITHOUT trusting the caller's identity yet.
        #    We look up by the Basic username (owner) so cross-owner probes never
        #    resolve to someone else's cache. Parse username first for lookup.
        auth_header = request.headers.get("authorization")
        # Peek the username for subject resolution (verification happens next).
        from patent_mcp_server._auth_provider import _parse_basic
        creds = _parse_basic(auth_header)
        token = None
        if creds is not None:
            entry = store.find_by_subject(creds[0], subject)
            token = entry.token if entry is not None else None

        # 2. Authenticate the Basic credential against that cache token.
        ident = _auth.resolve_identity(auth_header, token)
        if isinstance(ident, AuthError):
            _log.info("[dav] %s %s/%s owner=? status=%d", method, subject, rel,
                      ident.status)
            return _dav_error(ident.status, ident.code, ident.detail,
                              www_authenticate=ident.www_authenticate)

        # 3. Ownership check (cross-owner -> 403, no fallback).
        if not _auth.owns(ident, token):
            _log.info("[dav] %s %s/%s owner=%s status=403", method, subject, rel,
                      ident.owner)
            return _dav_error(403, "forbidden",
                              "identity does not own this subject cache")

        # 4. Dispatch the DAV method against the resolved token namespace.
        #    base_href / mount_prefix MUST reflect the path the CLIENT actually
        #    used, not the env gateway prefix: a direct localhost caller hits
        #    `/dav/...` (no prefix) while a gateway caller may carry `/patentmcp`.
        #    Baking PATENTS_GATEWAY_PREFIX into the returned href broke rclone
        #    (PROPFIND hrefs不對 → empty listing) and mis-flagged same-token MOVE
        #    as cross_token (Destination needle不匹配) — integration bug 5.5.
        #    Derive base_href by stripping the matched rel off the real req path;
        #    keep mount_prefix as the bare mount so _dest_rel's find() stays
        #    prefix-agnostic across direct/gateway callers.
        req_path = request.url.path
        rel_stripped = rel.rstrip("/")
        req_stripped = req_path.rstrip("/")
        if rel_stripped and req_stripped.endswith(rel_stripped):
            base_href = req_stripped[: len(req_stripped) - len(rel_stripped)]
        else:
            base_href = req_path
        if not base_href.endswith("/"):
            base_href += "/"
        body = await request.body()
        status, hdrs, out = _dav_handler.handle(
            method, token=token, rel=rel, subject=subject, owner=ident.owner,
            mount_prefix=_DAV_MOUNT_PREFIX, base_href=base_href,
            body=body, headers=dict(request.headers),
        )
        _log.info("[dav] %s %s/%s owner=%s status=%d", method, subject, rel,
                  ident.owner, status)
        return Response(out, status_code=status, headers=hdrs)

    app.router.routes.extend([
        Route("/", landing, methods=["GET"]),
        # WebDAV working-cache face (DD-4). Collection root + members. One route
        # each so Starlette matches /dav/{subject} and /dav/{subject}/{rel...}.
        Route(f"{_DAV_MOUNT_PREFIX}/{{subject}}", dav, methods=_dav.DAV_METHODS),
        Route(f"{_DAV_MOUNT_PREFIX}/{{subject}}/{{rel:path}}", dav,
              methods=_dav.DAV_METHODS),
        # /webdav alias for the SAME dav() handler (DD-4). base_href is derived
        # from the real request path, so one handler serves both mount prefixes
        # correctly; kept alongside /dav so existing rclone clients don't break.
        Route("/webdav/{subject}", dav, methods=_dav.DAV_METHODS),
        Route("/webdav/{subject}/{rel:path}", dav, methods=_dav.DAV_METHODS),
        # Standard liveness path (R8.3) + back-compat alias — same coroutine,
        # no duplicated logic (DD-2).
        Route("/health", health, methods=["GET"]),
        Route("/healthz", health, methods=["GET"]),
        # Machine-readable tool introspection (R8.1) — live registry (DD-1).
        Route("/tools", tools_index, methods=["GET"]),
        # JSON introspection kept at /tools.json (machine-readable, R8.1);
        # /tools is now the human index page linking to per-tool schema pages.
        Route("/tools.json", tools_json, methods=["GET"]),
        Route("/tools/{name}", tool_page, methods=["GET"]),
        # Legacy HTTP+SSE transport face (DD-5). Bare SseServerTransport wired
        # on THIS app — NOT a mounted sse_app() (which would double-enter the
        # streamable session-manager lifespan and crash).
        #   * /sse            — SSE stream, a Route (exact match, no Mount 307).
        #   * /sse/messages   — JSON-RPC POST sink, a Mount to the transport's
        #                       raw-ASGI handler (advertised to clients inside the
        #                       stream as `{prefix}/sse/messages`, see _sse init).
        Route("/sse", sse_stream, methods=["GET"]),
        Mount("/sse/messages", app=_sse.handle_post_message),
        Route("/files/{token}/blob/{rel:path}", blob, methods=["GET"]),
        Route(f"/skills/{_SKILL_NAME}.zip", skill_zip, methods=["GET"]),
    ])

    # Wrap the fully-routed Starlette app with the access-log middleware LAST, so
    # every route (MCP, SSE, DAV, files, skills, landing) is observed while the
    # Starlette app's own .router stays intact during route attachment above.
    app = _access_log_mw(app)
    return app


def serve(mcp, store, *, uds: Optional[str] = None,
          host: str = "127.0.0.1", port: Optional[int] = None) -> None:
    """Blocking: run the combined app over UDS and/or TCP from ONE process.

    Transport matrix (MCP integration standard R1.1/R1.2): for a containerized
    service UDS is the inward transport the same-host opencode daemon reaches
    (via bind mount), and TCP MAY be exposed additionally for direct IDE /
    cross-host access (R1.7) exposing the same MCP API. Pass `uds` and/or `port`:
      - uds + port → dual (recommended for a container that also wants IDE direct)
      - uds only   → gateway-fronted UDS service
      - port only  → TCP-localhost service

    IMPORTANT (why a single Server with multiple sockets, not two Servers):
    FastMCP's ``mcp.streamable_http_app()`` wires the StreamableHTTP
    session-manager lifespan INTO the app, so the app lifespan must run EXACTLY
    ONCE. Running two ``uvicorn.Server(...).serve()`` coroutines over the same
    app (the bodesign low-level-Server pattern) would enter the lifespan twice
    and double-enter ``session_manager.run()`` → crash. Instead we pre-bind one
    socket per transport and hand them to a SINGLE ``uvicorn.Server.run(sockets=
    [...])`` — one app, one lifespan, multiple listeners.
    """
    import socket as _socket
    import uvicorn

    if not uds and port is None:
        raise ValueError("serve() needs at least one inward transport: uds and/or port")

    # NOTE on /files handles: we deliberately do NOT set _file_server.FILE_BASE_URL
    # here, so handle download_urls stay RELATIVE (/files/...). Relative paths flow
    # correctly through the UDS gateway prefix (the conformant inward path); a
    # direct-TCP IDE resolves them against its own server base. Setting an absolute
    # TCP base would break the gateway-fronted UDS path, so relative is the safe
    # cross-transport default.
    app = build_app(mcp, store)
    sockets = []
    listening = []

    if port is not None:
        tcp_sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        tcp_sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        tcp_sock.bind((host, port))
        sockets.append(tcp_sock)
        listening.append(f"http://{host}:{port}")

    if uds:
        parent = os.path.dirname(uds)
        if parent:
            os.makedirs(parent, exist_ok=True)
        # Remove a stale socket file from a previous run (bind fails EADDRINUSE).
        if os.path.exists(uds):
            try:
                os.unlink(uds)
            except OSError as e:  # noqa: BLE001
                _log.warning("could not remove stale socket %s: %s", uds, e)
        # umask 0 so the socket file is created 0666 — any local user (incl. the
        # gateway under a rootful docker daemon) can connect (standard R7.3).
        old_umask = None
        try:
            old_umask = os.umask(0)
            _log.info("Setting process umask to 0 for UDS socket")
        except Exception as e:  # noqa: BLE001
            _log.warning("Failed to set umask to 0: %s", e)
        try:
            uds_sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
            uds_sock.bind(uds)
        finally:
            if old_umask is not None:
                os.umask(old_umask)
        sockets.append(uds_sock)
        listening.append(f"unix:{uds}")

    _log.info("patentmcp http listening on %s (/mcp, /files, /skills, /)",
              " + ".join(listening))
    # One Server, one app lifespan, N pre-bound sockets (see docstring).
    config = uvicorn.Config(app, log_level="info")
    uvicorn.Server(config).run(sockets=sockets)
