"""Token store for the patents-mcp file API — ported from docxmcp (same contract).

Mirrors docxmcp's _token_store.py so retrieval artifacts (excel/PDF/figures/
full-text) are delivered exactly the docxmcp way: an opaque `tok_<32>` token
whose bytes live under ``<root>/<token>/<filename>`` and are downloaded via
``/files/{token}/blob/{rel}``. Copy-by-reference (`from_token`) lets the
document side pull a patent artifact straight into a docx/pptx package without
re-encoding it through the model context.

Set ``PATENTS_TOKEN_SESSIONS_ROOT`` to docxmcp's ``DOCXMCP_TOKEN_SESSIONS_ROOT``
to share one physical store across both servers (format is rehydrate-compatible:
docxmcp's rehydrate falls back to file-stat for foreign sidecars).
"""
from __future__ import annotations

import base64
import contextlib
import dataclasses
import hashlib
import io
import json
import logging
import os
import secrets
import shutil
import threading
import time
from pathlib import Path
from typing import Any, BinaryIO, Iterator, Optional

_log = logging.getLogger("patents_mcp.token_store")

_META_NAME = ".patents-mcp-meta.json"

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent  # src/pkg/ → repo root
SESSIONS_ROOT = Path(
    os.environ.get("PATENTS_TOKEN_SESSIONS_ROOT", str(_REPO_ROOT / ".tmp" / "sessions"))
)

DEFAULT_TTL_SECONDS = int(os.environ.get("PATENTS_TOKEN_TTL_SECONDS", "3600"))
DEFAULT_SIZE_CAP_BYTES = int(
    os.environ.get("PATENTS_TOKEN_SIZE_CAP_BYTES", str(1024 * 1024 * 1024))
)

TOKEN_PREFIX = "tok_"
TOKEN_RANDOM_BYTES = 20
TOKEN_LENGTH = len(TOKEN_PREFIX) + 32


class TokenStoreError(Exception):
    pass


class TokenNotFoundError(TokenStoreError):
    pass


class StagingError(TokenStoreError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message)
        self.code = code
        self.message = message


def _generate_token() -> str:
    raw = secrets.token_bytes(TOKEN_RANDOM_BYTES)
    encoded = base64.b32encode(raw).decode("ascii").rstrip("=")
    assert len(encoded) == 32, f"unexpected base32 length: {len(encoded)}"
    return TOKEN_PREFIX + encoded


@dataclasses.dataclass
class TokenEntry:
    token: str
    filename: str
    sha256: str
    size_bytes: int
    created_at: float
    last_used_at: float
    root: Path = SESSIONS_ROOT

    @property
    def dir_path(self) -> Path:
        return self.root / self.token

    @property
    def file_path(self) -> Path:
        return self.dir_path / self.filename

    def download_url(self, rel: Optional[str] = None) -> str:
        return f"/files/{self.token}/blob/{rel or self.filename}"


class TokenStore:
    def __init__(
        self,
        *,
        sessions_root: Path = SESSIONS_ROOT,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        size_cap_bytes: int = DEFAULT_SIZE_CAP_BYTES,
    ) -> None:
        self._root = sessions_root
        self._ttl = ttl_seconds
        self._size_cap = size_cap_bytes
        self._entries: dict[str, TokenEntry] = {}
        self._total_bytes = 0
        self._lock = threading.RLock()
        self._root.mkdir(parents=True, exist_ok=True)
        self.rehydrate()

    # ── persistence ─────────────────────────────────────────────────
    def _write_meta(self, entry: TokenEntry) -> None:
        try:
            (entry.dir_path / _META_NAME).write_text(
                json.dumps({
                    "token": entry.token, "filename": entry.filename,
                    "sha256": entry.sha256, "size_bytes": entry.size_bytes,
                    "created_at": entry.created_at,
                }),
                encoding="utf-8",
            )
        except OSError:
            _log.warning("token_meta_write_failed token=%s", entry.token)

    def rehydrate(self) -> int:
        loaded = 0
        for entry_dir in sorted(self._root.glob(f"{TOKEN_PREFIX}*")):
            if not entry_dir.is_dir():
                continue
            token = entry_dir.name
            with self._lock:
                if token in self._entries:
                    continue
            meta_path = entry_dir / _META_NAME
            try:
                if meta_path.is_file():
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    filename = meta.get("filename", "")
                    sha256 = meta.get("sha256", "")
                    size_bytes = int(meta.get("size_bytes", 0))
                    created_at = float(meta.get("created_at", 0.0))
                else:
                    files = [p for p in entry_dir.rglob("*")
                             if p.is_file() and p.name != _META_NAME]
                    if not files:
                        continue
                    primary = max(files, key=lambda p: p.stat().st_size)
                    filename = primary.name if len(files) == 1 else ""
                    sha256 = ""
                    size_bytes = sum(p.stat().st_size for p in files)
                    created_at = primary.stat().st_mtime
                data_mtime = max(
                    (p.stat().st_mtime for p in entry_dir.rglob("*") if p.is_file()),
                    default=created_at,
                )
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            entry = TokenEntry(
                token=token, filename=filename, sha256=sha256,
                size_bytes=size_bytes, created_at=created_at,
                last_used_at=data_mtime, root=self._root,
            )
            with self._lock:
                self._entries[token] = entry
                self._total_bytes += size_bytes
            loaded += 1
        if loaded:
            self.reap_expired()
            with self._lock:
                self._evict_if_over_cap()
        return loaded

    # ── put / resolve / delete ──────────────────────────────────────
    def put(self, source: BinaryIO, filename: str) -> TokenEntry:
        if not filename or "/" in filename or "\\" in filename or filename in (".", ".."):
            raise TokenStoreError(f"invalid filename: {filename!r}")
        token = _generate_token()
        entry_dir = self._root / token
        entry_dir.mkdir(parents=True, exist_ok=False)
        target = entry_dir / filename
        hasher = hashlib.sha256()
        size = 0
        try:
            with target.open("wb") as out:
                while True:
                    chunk = source.read(64 * 1024)
                    if not chunk:
                        break
                    hasher.update(chunk)
                    out.write(chunk)
                    size += len(chunk)
        except Exception:
            shutil.rmtree(entry_dir, ignore_errors=True)
            raise
        now = time.time()
        entry = TokenEntry(
            token=token, filename=filename, sha256=hasher.hexdigest(),
            size_bytes=size, created_at=now, last_used_at=now, root=self._root,
        )
        with self._lock:
            self._entries[token] = entry
            self._total_bytes += size
            self._evict_if_over_cap()
        self._write_meta(entry)
        return entry

    def put_bytes(self, data: bytes, filename: str) -> TokenEntry:
        """Convenience: mint a token from an in-memory bytes payload."""
        return self.put(io.BytesIO(data), filename)

    def resolve(self, token: str) -> TokenEntry:
        with self._lock:
            entry = self._entries.get(token)
            if entry is None:
                raise TokenNotFoundError(f"token_not_found: {token}")
            entry.last_used_at = time.time()
            return entry

    def _safe_target(self, dir_path: Path, rel: str) -> Path:
        if not isinstance(rel, str) or not rel:
            raise StagingError("STAGE_BAD_PATH", "rel must be a non-empty string")
        if rel.startswith("/"):
            raise StagingError("STAGE_PATH_ABSOLUTE", f"rel must not be absolute: {rel!r}")
        root_resolved = dir_path.resolve()
        target = (dir_path / rel).resolve()
        try:
            target.relative_to(root_resolved)
        except ValueError as exc:
            raise StagingError(
                "STAGE_PATH_TRAVERSAL", f"path escapes token namespace: {rel!r}"
            ) from exc
        return target

    def blob_path(self, token: str, rel: str) -> Path:
        """Resolve {token, rel} to an on-disk file path for the HTTP blob server."""
        entry = self.resolve(token)
        target = self._safe_target(entry.dir_path, rel)
        if not target.is_file():
            raise TokenNotFoundError(f"blob_not_found: {token}/{rel}")
        return target

    def write_file(self, token: str, rel: str, data: bytes,
                   *, max_bytes: int = 64 * 1024 * 1024) -> int:
        """Write/overwrite a single file at rel inside an existing token dir."""
        if len(data) > max_bytes:
            raise StagingError("STAGE_FILE_TOO_LARGE", f"file {rel!r} exceeds cap")
        entry = self.resolve(token)
        target = self._safe_target(entry.dir_path, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        old_size = target.stat().st_size if target.exists() else 0
        tmp = target.with_name(target.name + f".tmp-{secrets.token_hex(4)}")
        try:
            tmp.write_bytes(bytes(data))
            os.replace(tmp, target)
        except OSError:
            with contextlib.suppress(OSError):
                tmp.unlink()
            raise
        with self._lock:
            entry.size_bytes = max(0, entry.size_bytes - old_size) + len(data)
            self._total_bytes += len(data) - old_size
        return len(data)

    def list_files(self, token: str) -> list[dict[str, Any]]:
        entry = self.resolve(token)
        root = entry.dir_path.resolve()
        out: list[dict[str, Any]] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.name == _META_NAME:
                continue
            rel = str(path.relative_to(root))
            st = path.stat()
            out.append({
                "rel": rel, "size": st.st_size, "mtime": st.st_mtime,
                "download_url": f"/files/{token}/blob/{rel}",
            })
        return out

    def delete(self, token: str) -> None:
        with self._lock:
            entry = self._entries.pop(token, None)
            if entry is None:
                return
            self._total_bytes -= entry.size_bytes
        shutil.rmtree(entry.dir_path, ignore_errors=True)

    # ── reaper ──────────────────────────────────────────────────────
    def reap_expired(self) -> int:
        cutoff = time.time() - self._ttl
        evicted: list[TokenEntry] = []
        with self._lock:
            for token, entry in list(self._entries.items()):
                if entry.last_used_at < cutoff:
                    self._entries.pop(token, None)
                    self._total_bytes -= entry.size_bytes
                    evicted.append(entry)
        for entry in evicted:
            shutil.rmtree(entry.dir_path, ignore_errors=True)
        return len(evicted)

    def _evict_if_over_cap(self) -> None:
        if self._total_bytes <= self._size_cap:
            return
        ordered = sorted(self._entries.values(), key=lambda e: e.last_used_at)
        evicted: list[TokenEntry] = []
        for entry in ordered:
            if self._total_bytes <= self._size_cap:
                break
            self._entries.pop(entry.token, None)
            self._total_bytes -= entry.size_bytes
            evicted.append(entry)
        for entry in evicted:
            shutil.rmtree(entry.dir_path, ignore_errors=True)

    def stats(self) -> dict:
        with self._lock:
            return {
                "active_tokens": len(self._entries),
                "storage_bytes": self._total_bytes,
                "ttl_seconds": self._ttl,
                "size_cap_bytes": self._size_cap,
            }

    def __iter__(self) -> Iterator[TokenEntry]:
        with self._lock:
            return iter(list(self._entries.values()))


_default_store: Optional[TokenStore] = None


def default_store() -> TokenStore:
    global _default_store
    if _default_store is None:
        _default_store = TokenStore()
    return _default_store
