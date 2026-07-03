"""HTTP Basic auth for the WebDAV working-cache face (DD-6).

The MCP face is protected by the UDS + gateway trust boundary, but the WebDAV
face — including the additionally-published TCP :8000 — is reachable by any
local client, so every DAV request MUST carry a per-owner Basic credential.

`cache_provision` mints a high-entropy credential per (owner, subject) cache and
stores only its sha256 hash on the token entry (TokenStore.set_credential). This
module verifies the incoming Basic header against that hash via
`TokenStore.verify_credential` (hmac.compare_digest), then enforces ownership.

天條 §11: NO silent identity fallback. A missing/invalid credential is a typed
401 (with WWW-Authenticate: Basic); a cross-owner access is a typed 403. We never
resolve to a "default" / "first" / "global active" identity.
"""
from __future__ import annotations

import base64
import binascii
import dataclasses
from typing import Optional


DAV_REALM = "patentmcp-webdav"


@dataclasses.dataclass
class Identity:
    """A resolved DAV caller identity (the Basic username)."""
    owner: str


@dataclasses.dataclass
class AuthError:
    """A typed auth failure. `status` is the HTTP code the DAV layer emits."""
    status: int          # 401 (no/invalid credential) | 403 (cross-owner)
    code: str            # machine-readable
    detail: str
    www_authenticate: bool = False   # emit WWW-Authenticate: Basic header


def _parse_basic(header: Optional[str]) -> Optional[tuple[str, str]]:
    """Return (username, password) from an Authorization: Basic header, else None."""
    if not header:
        return None
    parts = header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "basic":
        return None
    try:
        decoded = base64.b64decode(parts[1].strip(), validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    if ":" not in decoded:
        return None
    user, pw = decoded.split(":", 1)
    if not user:
        return None
    return user, pw


class AuthProvider:
    """Basic-auth provider backed by the token store's per-owner credentials.

    A credential is verified against the specific cache token for the subject in
    the request path. This binds "who you are" to "which cache you may touch" in
    one check: the password only verifies against the cache whose owner minted
    it, so a valid credential for cache A cannot authenticate against cache B.
    """

    def __init__(self, store) -> None:
        self._store = store

    def resolve_identity(self, authorization: Optional[str],
                         token: Optional[str]) -> Identity | AuthError:
        """Resolve the Basic credential against the given cache `token`.

        `token` is the deliverable-cache token the request path resolved to
        (subject → token via TokenStore.find_by_subject, done by the caller). We
        verify the presented password against THAT token's credential_hash.
        """
        creds = _parse_basic(authorization)
        if creds is None:
            return AuthError(
                status=401, code="AUTH_REQUIRED",
                detail="Basic credential required for the WebDAV face",
                www_authenticate=True,
            )
        user, pw = creds
        if token is None:
            # Subject did not resolve to a cache. Do not leak existence; treat as
            # an auth failure (401) rather than 404 — no identity fallback.
            return AuthError(
                status=401, code="AUTH_FAILED",
                detail="no cache matches these credentials",
                www_authenticate=True,
            )
        if not self._store.verify_credential(token, pw):
            return AuthError(
                status=401, code="AUTH_FAILED",
                detail="invalid Basic credential",
                www_authenticate=True,
            )
        return Identity(owner=user)

    def owns(self, identity: Identity, token: str) -> bool:
        """True iff `identity` is the owner recorded on the cache `token`.

        A valid credential proves the caller holds the cache secret; this second
        check enforces that the Basic username also matches the cache's
        owner_identity, so a cross-owner request (even with a leaked password) is
        rejected 403 rather than silently accepted.
        """
        try:
            entry = self._store.resolve(token)
        except Exception:  # noqa: BLE001 — unknown token ⇒ not owned
            return False
        owner = entry.owner_identity
        return owner is not None and owner == identity.owner
