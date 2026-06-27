"""HTTP blob server for the patents-mcp token store.

Serves ``/files/{token}/blob/{rel}`` exactly like docxmcp, so the handles our
tools return are directly downloadable. Runs in a background thread alongside
the stdio MCP loop. Bind is localhost:PATENTS_FILES_PORT (default 8077);
set the port to 0 to disable the server (handles then carry only the on-disk
path for shared-filesystem / from_token consumption).
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Optional

_log = logging.getLogger("patents_mcp.file_server")

_SERVICE_MARKER = "patents-mcp-files"

# Set once the server is up so tools can build absolute download URLs.
FILE_BASE_URL: Optional[str] = None


def _free_port() -> int:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _confirm_up(base: str, timeout: float = 4.0) -> bool:
    """Poll /healthz until OUR service marker answers (guards against another
    service already squatting the port)."""
    import time
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base + "/healthz", timeout=0.5) as r:
                import json
                body = json.loads(r.read().decode("utf-8"))
                if body.get("service") == _SERVICE_MARKER:
                    return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.1)
    return False


def _make_app(store):
    from starlette.applications import Starlette
    from starlette.responses import FileResponse, JSONResponse
    from starlette.routing import Route

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

    return Starlette(routes=[
        Route("/files/{token}/blob/{rel:path}", blob),
        Route("/healthz", health),
    ])


def start_file_server(store, host: str = "127.0.0.1",
                      port: Optional[int] = None) -> Optional[str]:
    """Start the blob server in a daemon thread. Returns its base URL (or None
    if disabled). Idempotent-ish: callers should invoke once at startup."""
    global FILE_BASE_URL
    if FILE_BASE_URL is not None:
        return FILE_BASE_URL  # already started
    env_port = os.environ.get("PATENTS_FILES_PORT")
    if env_port == "0":
        _log.info("file server disabled (PATENTS_FILES_PORT=0)")
        return None
    import uvicorn

    app = _make_app(store)
    # Try the requested/env port first, then auto-pick free ports (the default
    # 8077 may be squatted by another local service — observed 'bodesign').
    candidates = []
    if port is not None:
        candidates.append(port)
    elif env_port:
        candidates.append(int(env_port))
    candidates += [_free_port() for _ in range(3)]

    for cand in candidates:
        config = uvicorn.Config(app, host=host, port=cand, log_level="warning")
        server = uvicorn.Server(config)
        threading.Thread(target=server.run, daemon=True,
                         name=f"patents-file-server:{cand}").start()
        base = f"http://{host}:{cand}"
        if _confirm_up(base):
            FILE_BASE_URL = base
            _log.info("file server listening on %s", base)
            return base
        _log.warning("port %d unavailable or squatted, trying next", cand)
    _log.error("could not start file server on any candidate port")
    return None


def download_url(token: str, rel: str) -> str:
    """Absolute URL if the server is up, else the relative docxmcp-style path."""
    rel_path = f"/files/{token}/blob/{rel}"
    return (FILE_BASE_URL + rel_path) if FILE_BASE_URL else rel_path
