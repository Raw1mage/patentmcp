"""Protocol-native resource face for the patents-mcp token store (standard R17.1(c)).

R17.1(c) makes ``resources/read`` a MUST: every produced binary must be
retrievable on the portable MCP floor (R0/R2) WITHOUT a host-private extension
(``/files/{token}/blob`` or the WebDAV ``/dav`` face). Those extensions stay as
host accelerators; this module adds the portable floor beside them.

Design (plan patentmcp_r17-minimum-operational-toolset, DD-1):

- URI scheme ``patent://{token}/{rel}`` uniquely names one artifact in the token
  store. ``read`` delegates to ``TokenStore.blob_path(token, rel)``, which already
  resolves + traversal-checks the path (``_safe_target``) and raises fail-loud on
  an unknown token / missing rel / path escaping the namespace — so the resource
  read inherits the exact same safety as the blob face (single source, zero drift).
- ``resources/list`` must MIRROR the live token store (artifacts are minted at
  runtime), so it is generated dynamically from ``store.list_files`` over every
  live entry — not a static registration.

Nothing here removes or changes the blob / WebDAV faces.
"""
from __future__ import annotations

import mimetypes
from typing import TYPE_CHECKING
from urllib.parse import quote, unquote

if TYPE_CHECKING:  # avoid import cycle / heavy import at module load
    from patent_mcp_server._token_store import TokenStore

RESOURCE_SCHEME = "patent"
_URI_PREFIX = f"{RESOURCE_SCHEME}://"


def build_uri(token: str, rel: str) -> str:
    """Compose ``patent://{token}/{rel}`` with each rel segment percent-encoded.

    ``token`` is an opaque ``tok_*`` (base32, URL-safe already); ``rel`` may carry
    sub-directories (``sub/b.png``) whose ``/`` are structural and kept, while each
    segment's other reserved chars are encoded so the URI round-trips.
    """
    safe_rel = "/".join(quote(seg, safe="") for seg in rel.split("/"))
    return f"{_URI_PREFIX}{token}/{safe_rel}"


def parse_uri(uri: str) -> tuple[str, str]:
    """Inverse of :func:`build_uri`. Returns ``(token, rel)``.

    Fail-loud (``ValueError``) on a non-``patent://`` scheme or a missing rel — the
    SDK surfaces this as a resource error, never a silent empty read (天条 §11).
    """
    if not uri.startswith(_URI_PREFIX):
        raise ValueError(f"not a {RESOURCE_SCHEME}:// resource URI: {uri!r}")
    remainder = uri[len(_URI_PREFIX):]
    token, sep, rel = remainder.partition("/")
    if not token or not sep or not rel:
        raise ValueError(
            f"malformed {RESOURCE_SCHEME}:// URI (expected {RESOURCE_SCHEME}://<token>/<rel>): {uri!r}"
        )
    decoded_rel = "/".join(unquote(seg) for seg in rel.split("/"))
    return token, decoded_rel


def guess_mime(rel: str) -> str:
    """Best-effort MIME from the rel suffix; default application/octet-stream."""
    mime, _ = mimetypes.guess_type(rel)
    return mime or "application/octet-stream"


def read_resource_bytes(store: "TokenStore", uri: str) -> bytes:
    """Resolve a ``patent://`` URI to its bytes via the traversal-safe blob path.

    Reuses ``TokenStore.blob_path`` so an unknown token / missing rel / traversal
    attempt raises the store's own fail-loud error (``TokenNotFoundError`` /
    ``StagingError``), which the SDK converts into a resource error. No fallback.
    """
    token, rel = parse_uri(uri)
    path = store.blob_path(token, rel)  # raises on unknown / traversal
    return path.read_bytes()


def list_resource_descriptors(store: "TokenStore") -> list[dict]:
    """Enumerate every live token-store artifact as a resource descriptor.

    Mirrors the live store: one descriptor per file returned by
    ``store.list_files`` across every live entry. Each descriptor:
    ``{uri, name, mime_type, size}``. Cold path (client discovery), not a hot loop.
    """
    out: list[dict] = []
    for entry in store:
        try:
            files = store.list_files(entry.token)
        except Exception:  # noqa: BLE001 — a reaped/racing entry is simply skipped
            continue
        for f in files:
            rel = f["rel"]
            out.append({
                "uri": build_uri(entry.token, rel),
                "name": rel,
                "mime_type": guess_mime(rel),
                "size": f.get("size"),
            })
    return out
