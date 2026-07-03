"""WebDAV class-2 method handlers over a single deliverable-cache token dir (DD-4).

Each DAV request has already been resolved by the mount layer (_http_app) to a
concrete cache `token` and an authenticated `Identity`; this module implements
the method table against that token's namespace using the TokenStore primitives
(blob_path / write_file / list_files / mkdir / move / delete). Traversal defence
and size caps are inherited from the store's `_safe_target`.

Method table (DD-4):
  OPTIONS   → DAV: 1,2 + Allow
  PROPFIND  → Depth 0/1 multistatus XML from list_files
  GET       → blob_path
  PUT       → write_file
  DELETE    → unlink within token dir
  MKCOL     → store.mkdir
  MOVE      → store.move (Destination must be same subject/token else 403)
  LOCK      → in-memory lock table (TTL), returns a lock token
  UNLOCK    → release lock

Lock table is in-memory (DD-4 R4): a restart drops locks (standard WebDAV
behaviour); every lock carries a TTL. A resource locked by one (owner, lock
token) rejects a conflicting write from anyone else with 423 Locked.

天條 §11 no-silent-fallback: cross-token MOVE → 403, traversal → typed 4xx,
lock conflict → 423. Never operate on a different token than the one resolved.
"""
from __future__ import annotations

import dataclasses
import html
import secrets
import time
from typing import Optional
from urllib.parse import unquote, urlsplit
from xml.sax.saxutils import escape as _xml_escape


DAV_METHODS = [
    "OPTIONS", "PROPFIND", "GET", "HEAD", "PUT", "DELETE",
    "MKCOL", "MOVE", "LOCK", "UNLOCK",
]

DEFAULT_LOCK_TTL_SECONDS = 3600


# ── in-memory lock table ─────────────────────────────────────────────
@dataclasses.dataclass
class _Lock:
    lock_token: str
    owner: str
    token: str          # cache token
    rel: str
    expires_at: float


class LockTable:
    """Process-local WebDAV lock registry (class-2). TTL-bounded; lost on restart."""

    def __init__(self) -> None:
        self._locks: dict[tuple[str, str], _Lock] = {}   # (token, rel) → _Lock

    def _prune(self) -> None:
        now = time.time()
        for key in [k for k, lk in self._locks.items() if lk.expires_at <= now]:
            self._locks.pop(key, None)

    def find(self, token: str, rel: str) -> Optional[_Lock]:
        self._prune()
        return self._locks.get((token, rel))

    def acquire(self, token: str, rel: str, owner: str,
                ttl: int = DEFAULT_LOCK_TTL_SECONDS) -> Optional[_Lock]:
        """Acquire a lock; None if already held by a live conflicting lock."""
        self._prune()
        existing = self._locks.get((token, rel))
        if existing is not None and existing.owner != owner:
            return None
        lock = _Lock(
            lock_token=f"opaquelocktoken:{secrets.token_hex(16)}",
            owner=owner, token=token, rel=rel,
            expires_at=time.time() + ttl,
        )
        self._locks[(token, rel)] = lock
        return lock

    def release(self, token: str, rel: str, lock_token: str) -> bool:
        self._prune()
        existing = self._locks.get((token, rel))
        if existing is None or existing.lock_token != lock_token:
            return False
        self._locks.pop((token, rel), None)
        return True

    def blocks_write(self, token: str, rel: str, owner: str,
                     lock_token: Optional[str]) -> bool:
        """True iff a live lock by a DIFFERENT owner (and not the presented lock
        token) forbids a write at rel."""
        lk = self.find(token, rel)
        if lk is None:
            return False
        if lk.owner == owner:
            return False
        if lock_token and lk.lock_token == lock_token:
            return False
        return True


# ── multistatus XML composer ─────────────────────────────────────────
def _propstat_response(href: str, *, is_dir: bool, size: int = 0,
                       mtime: float = 0.0) -> str:
    from email.utils import formatdate
    lastmod = formatdate(mtime, usegmt=True) if mtime else ""
    if is_dir:
        restype = "<D:resourcetype><D:collection/></D:resourcetype>"
        length = ""
    else:
        restype = "<D:resourcetype/>"
        length = f"<D:getcontentlength>{size}</D:getcontentlength>"
    return (
        "<D:response>"
        f"<D:href>{_xml_escape(href)}</D:href>"
        "<D:propstat><D:prop>"
        f"{restype}{length}"
        f"<D:getlastmodified>{_xml_escape(lastmod)}</D:getlastmodified>"
        "</D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat>"
        "</D:response>"
    )


def build_multistatus(base_href: str, entries: list[dict], *,
                      include_self: bool = True) -> str:
    """Compose a well-formed 207 multistatus body. `base_href` is the collection
    href (…/dav/{subject}/); entries are list_files() dicts (rel/size/mtime)."""
    base = base_href if base_href.endswith("/") else base_href + "/"
    parts = ['<?xml version="1.0" encoding="utf-8"?>',
             '<D:multistatus xmlns:D="DAV:">']
    seen_dirs: set[str] = set()
    if include_self:
        parts.append(_propstat_response(base, is_dir=True))
    for e in entries:
        rel = e["rel"]
        # synthesize intermediate collection responses for nested rels
        segs = rel.split("/")
        for i in range(len(segs) - 1):
            d = "/".join(segs[: i + 1])
            if d not in seen_dirs:
                seen_dirs.add(d)
                parts.append(_propstat_response(base + d + "/", is_dir=True))
        parts.append(_propstat_response(
            base + rel, is_dir=False, size=e.get("size", 0),
            mtime=e.get("mtime", 0.0)))
    parts.append("</D:multistatus>")
    return "".join(parts)


def _lockdiscovery_xml(lock: _Lock) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<D:prop xmlns:D="DAV:"><D:lockdiscovery><D:activelock>'
        "<D:locktype><D:write/></D:locktype>"
        "<D:lockscope><D:exclusive/></D:lockscope>"
        "<D:depth>0</D:depth>"
        f"<D:owner>{_xml_escape(lock.owner)}</D:owner>"
        f"<D:timeout>Second-{max(0, int(lock.expires_at - time.time()))}</D:timeout>"
        "<D:locktoken><D:href>"
        f"{_xml_escape(lock.lock_token)}</D:href></D:locktoken>"
        "</D:activelock></D:lockdiscovery></D:prop>"
    )


# ── method dispatcher ────────────────────────────────────────────────
class DavHandler:
    """Executes one DAV method against a resolved (token, rel). Returns
    (status_code, headers, body_bytes). Pure over the store + lock table so it is
    trivially unit-testable without a live server."""

    def __init__(self, store, locks: LockTable) -> None:
        self._store = store
        self._locks = locks

    def _dest_rel(self, destination: Optional[str], subject: str,
                  mount_prefix: str) -> Optional[str]:
        """Extract the same-subject rel from a Destination header, or None if it
        targets a different subject/token (cross-token move → forbidden)."""
        if not destination:
            return None
        path = unquote(urlsplit(destination).path)
        needle = f"{mount_prefix}/{subject}/"
        idx = path.find(needle)
        if idx == -1:
            return None
        return path[idx + len(needle):].lstrip("/") or None

    def handle(self, method: str, *, token: str, rel: str, subject: str,
               owner: str, mount_prefix: str, base_href: str,
               body: bytes = b"", headers: Optional[dict] = None):
        headers = {k.lower(): v for k, v in (headers or {}).items()}
        m = method.upper()
        if m == "OPTIONS":
            return self._options()
        if m == "PROPFIND":
            return self._propfind(token, rel, base_href, headers)
        if m in ("GET", "HEAD"):
            return self._get(token, rel, head=(m == "HEAD"))
        if m == "PUT":
            return self._put(token, rel, owner, body, headers)
        if m == "DELETE":
            return self._delete(token, rel, owner, headers)
        if m == "MKCOL":
            return self._mkcol(token, rel)
        if m == "MOVE":
            return self._move(token, rel, subject, owner, mount_prefix, headers)
        if m == "LOCK":
            return self._lock(token, rel, owner, headers)
        if m == "UNLOCK":
            return self._unlock(token, rel, headers)
        return (405, {"Allow": ", ".join(DAV_METHODS)}, b"")

    # ── individual methods ──
    def _options(self):
        return (200, {
            "DAV": "1,2",
            "Allow": ", ".join(DAV_METHODS),
            "MS-Author-Via": "DAV",
            "Content-Length": "0",
        }, b"")

    def _propfind(self, token, rel, base_href, headers):
        depth = headers.get("depth", "1")
        try:
            files = self._store.list_files(token)
        except Exception as e:  # noqa: BLE001
            return self._err(404, "not_found", str(e))
        if rel:
            # PROPFIND on a specific member
            match = [f for f in files if f["rel"] == rel]
            children = [f for f in files
                        if f["rel"].startswith(rel + "/")] if depth != "0" else []
            if not match and not children:
                # maybe a collection prefix
                if not any(f["rel"].startswith(rel + "/") for f in files):
                    return self._err(404, "not_found", f"no such resource: {rel}")
            entries = match + children if depth != "0" else match
            body = build_multistatus(base_href.rstrip("/"),
                                     [{**e, "rel": e["rel"]} for e in entries],
                                     include_self=False)
        else:
            entries = files if depth != "0" else []
            body = build_multistatus(base_href, entries, include_self=True)
        return (207, {"Content-Type": 'application/xml; charset="utf-8"'},
                body.encode("utf-8"))

    def _get(self, token, rel, *, head):
        if not rel:
            return self._err(400, "is_collection", "cannot GET a collection")
        try:
            path = self._store.blob_path(token, rel)
        except Exception as e:  # noqa: BLE001
            return self._err(404, "not_found", str(e))
        data = b"" if head else path.read_bytes()
        st = path.stat()
        from email.utils import formatdate
        hdrs = {
            "Content-Type": "application/octet-stream",
            "Content-Length": str(st.st_size),
            "Last-Modified": formatdate(st.st_mtime, usegmt=True),
        }
        return (200, hdrs, data)

    def _put(self, token, rel, owner, body, headers):
        if not rel:
            return self._err(400, "is_collection", "cannot PUT onto a collection")
        lock_token = _if_lock_token(headers.get("if"))
        if self._locks.blocks_write(token, rel, owner, lock_token):
            return self._err(423, "locked", f"resource is locked: {rel}")
        try:
            self._store.write_file(token, rel, body)
        except Exception as e:  # noqa: BLE001
            return self._store_err(e)
        return (201, {"Content-Length": "0"}, b"")

    def _delete(self, token, rel, owner, headers):
        if not rel:
            return self._err(400, "bad_request", "refusing to DELETE cache root")
        lock_token = _if_lock_token(headers.get("if"))
        if self._locks.blocks_write(token, rel, owner, lock_token):
            return self._err(423, "locked", f"resource is locked: {rel}")
        try:
            path = self._store.blob_path(token, rel)
        except Exception as e:  # noqa: BLE001
            return self._err(404, "not_found", str(e))
        try:
            path.unlink()
        except OSError as e:
            return self._err(500, "delete_failed", str(e))
        return (204, {"Content-Length": "0"}, b"")

    def _mkcol(self, token, rel):
        if not rel:
            return self._err(405, "method_not_allowed", "collection root exists")
        try:
            self._store.mkdir(token, rel)
        except Exception as e:  # noqa: BLE001
            return self._store_err(e)
        return (201, {"Content-Length": "0"}, b"")

    def _move(self, token, rel, subject, owner, mount_prefix, headers):
        dest = headers.get("destination")
        dst_rel = self._dest_rel(dest, subject, mount_prefix)
        if dst_rel is None:
            # Destination missing OR targets a different subject/token.
            return self._err(403, "cross_token_move",
                             "MOVE Destination must stay within the same subject cache")
        lock_token = _if_lock_token(headers.get("if"))
        if (self._locks.blocks_write(token, rel, owner, lock_token)
                or self._locks.blocks_write(token, dst_rel, owner, lock_token)):
            return self._err(423, "locked", "source or destination is locked")
        try:
            self._store.move(token, rel, dst_rel)
        except Exception as e:  # noqa: BLE001
            return self._store_err(e)
        return (201, {"Content-Length": "0"}, b"")

    def _lock(self, token, rel, owner, headers):
        ttl = _parse_timeout(headers.get("timeout"))
        lock = self._locks.acquire(token, rel, owner, ttl=ttl)
        if lock is None:
            return self._err(423, "locked", f"already locked by another owner: {rel}")
        return (200, {
            "Content-Type": 'application/xml; charset="utf-8"',
            "Lock-Token": f"<{lock.lock_token}>",
        }, _lockdiscovery_xml(lock).encode("utf-8"))

    def _unlock(self, token, rel, headers):
        raw = headers.get("lock-token", "")
        lock_token = raw.strip().lstrip("<").rstrip(">")
        if self._locks.release(token, rel, lock_token):
            return (204, {"Content-Length": "0"}, b"")
        return self._err(409, "no_lock", "no matching lock to release")

    # ── error shaping ──
    def _err(self, status, code, detail):
        body = (f'<?xml version="1.0" encoding="utf-8"?>'
                f'<error xmlns="patentmcp"><code>{_xml_escape(code)}</code>'
                f'<detail>{_xml_escape(detail)}</detail></error>').encode("utf-8")
        hdrs = {"Content-Type": 'application/xml; charset="utf-8"'}
        return (status, hdrs, body)

    def _store_err(self, exc):
        code = getattr(exc, "code", None)
        if code in ("STAGE_PATH_TRAVERSAL", "STAGE_PATH_ABSOLUTE", "STAGE_BAD_PATH"):
            return self._err(400, code, str(getattr(exc, "message", exc)))
        if code == "STAGE_PATH_CONFLICT":
            return self._err(409, code, str(getattr(exc, "message", exc)))
        if code == "STAGE_FILE_TOO_LARGE":
            return self._err(413, code, str(getattr(exc, "message", exc)))
        return self._err(404, "not_found", str(exc))


def _if_lock_token(if_header: Optional[str]) -> Optional[str]:
    """Extract an opaquelocktoken from a WebDAV `If:` header, if present."""
    if not if_header:
        return None
    start = if_header.find("opaquelocktoken:")
    if start == -1:
        return None
    end = start
    while end < len(if_header) and if_header[end] not in ">) ":
        end += 1
    return if_header[start:end]


def _parse_timeout(timeout_header: Optional[str]) -> int:
    if not timeout_header:
        return DEFAULT_LOCK_TTL_SECONDS
    for part in timeout_header.split(","):
        part = part.strip().lower()
        if part.startswith("second-"):
            try:
                return max(1, int(part[len("second-"):]))
            except ValueError:
                continue
    return DEFAULT_LOCK_TTL_SECONDS
