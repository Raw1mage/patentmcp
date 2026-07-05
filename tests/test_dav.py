"""WebDAV cache face tests (group 5): auth 401/403, DAV method table, lock 423,
MOVE cross-token 403, PROPFIND multistatus, OPTIONS DAV:1,2. Uses Starlette
TestClient against build_app (the real app + real token store)."""
from __future__ import annotations

import base64
import importlib

import pytest

from patent_mcp_server import _dav
from patent_mcp_server._auth_provider import AuthProvider, AuthError, Identity
from patent_mcp_server._token_store import TokenStore


def _basic(user: str, pw: str) -> dict:
    raw = base64.b64encode(f"{user}:{pw}".encode()).decode()
    return {"Authorization": f"Basic {raw}"}


# ── unit: LockTable + multistatus + handler (no server) ──────────────
def test_options_dav_1_2():
    store = TokenStore(sessions_root=_tmp())
    h = _dav.DavHandler(store, _dav.LockTable())
    status, hdrs, _ = h.handle("OPTIONS", token="t", rel="", subject="s",
                               owner="alice", mount_prefix="/dav", base_href="/dav/s/")
    assert status == 200
    assert hdrs["DAV"] == "1,2"
    assert "PROPFIND" in hdrs["Allow"] and "LOCK" in hdrs["Allow"]


def test_lock_then_other_owner_put_423(tmp_path):
    store = TokenStore(sessions_root=tmp_path)
    entry = store.provision("q3", "alice")
    store.write_file(entry.token, "a.csv", b"x")
    locks = _dav.LockTable()
    h = _dav.DavHandler(store, locks)
    # alice locks
    s, hdrs, _ = h.handle("LOCK", token=entry.token, rel="a.csv", subject="q3",
                          owner="alice", mount_prefix="/dav", base_href="/dav/q3/")
    assert s == 200 and "Lock-Token" in hdrs
    # bob PUT -> 423 (TV-11)
    s2, _, _ = h.handle("PUT", token=entry.token, rel="a.csv", subject="q3",
                        owner="bob", mount_prefix="/dav", base_href="/dav/q3/",
                        body=b"y")
    assert s2 == 423
    # alice PUT still allowed
    s3, _, _ = h.handle("PUT", token=entry.token, rel="a.csv", subject="q3",
                        owner="alice", mount_prefix="/dav", base_href="/dav/q3/",
                        body=b"z")
    assert s3 == 201


def test_move_cross_token_rejected_403(tmp_path):
    store = TokenStore(sessions_root=tmp_path)
    entry = store.provision("q3", "alice")
    store.write_file(entry.token, "a.csv", b"x")
    h = _dav.DavHandler(store, _dav.LockTable())
    # Destination targets a DIFFERENT subject -> 403 (TV-10)
    s, _, _ = h.handle("MOVE", token=entry.token, rel="a.csv", subject="q3",
                       owner="alice", mount_prefix="/dav", base_href="/dav/q3/",
                       headers={"Destination": "http://h/dav/other/b.csv"})
    assert s == 403
    # same-subject rename works
    s2, _, _ = h.handle("MOVE", token=entry.token, rel="a.csv", subject="q3",
                        owner="alice", mount_prefix="/dav", base_href="/dav/q3/",
                        headers={"Destination": "http://h/dav/q3/b.csv"})
    assert s2 == 201
    assert store.blob_path(entry.token, "b.csv").read_bytes() == b"x"


def test_propfind_multistatus_wellformed(tmp_path):
    import xml.dom.minidom as minidom
    store = TokenStore(sessions_root=tmp_path)
    entry = store.provision("q3", "alice")
    store.write_file(entry.token, "chapters/c1.md", b"hello")
    h = _dav.DavHandler(store, _dav.LockTable())
    # Depth:1 on root lists DIRECT children only (the `chapters/` collection),
    # NOT the grandchild file — WebDAV clients (rclone) recurse one level at a
    # time. The old assertion expected the grandchild and thereby固化了 the
    # integration bug that broke rclone (5.5).
    s, hdrs, body = h.handle("PROPFIND", token=entry.token, rel="", subject="q3",
                             owner="alice", mount_prefix="/dav",
                             base_href="/dav/q3/", headers={"Depth": "1"})
    assert s == 207
    doc = minidom.parseString(body)  # raises on malformed XML
    assert doc.getElementsByTagName("D:response")
    assert b"chapters/" in body
    assert b"chapters/c1.md" not in body  # grandchild not at Depth:1
    # Descending into the collection reveals the file, and an EMPTY dir is visible
    store.mkdir(entry.token, "emptydir")
    s2, _, body2 = h.handle("PROPFIND", token=entry.token, rel="chapters",
                            subject="q3", owner="alice", mount_prefix="/dav",
                            base_href="/dav/q3/", headers={"Depth": "1"})
    assert s2 == 207 and b"chapters/c1.md" in body2
    s3, _, body3 = h.handle("PROPFIND", token=entry.token, rel="emptydir/",
                            subject="q3", owner="alice", mount_prefix="/dav",
                            base_href="/dav/q3/", headers={"Depth": "1"})
    assert s3 == 207  # empty MKCOL dir is found, not a false 404


# ── auth unit ────────────────────────────────────────────────────────
def test_auth_no_credential_401():
    store = TokenStore(sessions_root=_tmp())
    ap = AuthProvider(store)
    r = ap.resolve_identity(None, token=None)
    assert isinstance(r, AuthError) and r.status == 401 and r.www_authenticate


def test_auth_cross_owner_403(tmp_path):
    store = TokenStore(sessions_root=tmp_path)
    entry = store.provision("q3", "alice")
    store.set_credential(entry.token, "s3cret")
    ap = AuthProvider(store)
    # bob presents alice's correct password but is not the owner
    ident = ap.resolve_identity_ok = ap.resolve_identity(
        _auth_header("bob", "s3cret"), token=entry.token)
    # credential verifies (password correct) -> Identity(bob); owns() must fail
    assert isinstance(ident, Identity) and ident.owner == "bob"
    assert ap.owns(ident, entry.token) is False


def test_auth_wrong_password_401(tmp_path):
    store = TokenStore(sessions_root=tmp_path)
    entry = store.provision("q3", "alice")
    store.set_credential(entry.token, "s3cret")
    ap = AuthProvider(store)
    r = ap.resolve_identity(_auth_header("alice", "wrong"), token=entry.token)
    assert isinstance(r, AuthError) and r.status == 401


# ── integration via TestClient ───────────────────────────────────────
def _make_app(tmp_path):
    from starlette.testclient import TestClient
    from patent_mcp_server import _http_app
    from mcp.server.fastmcp import FastMCP
    store = TokenStore(sessions_root=tmp_path)
    mcp = FastMCP("test")
    app = _http_app.build_app(mcp, store)
    return TestClient(app, raise_server_exceptions=True), store


def test_dav_get_401_without_auth(tmp_path):
    client, store = _make_app(tmp_path)
    entry = store.provision("q3", "alice")
    store.set_credential(entry.token, "pw")
    store.write_file(entry.token, "a.csv", b"data")
    # TV-3: no auth -> 401 with WWW-Authenticate
    r = client.get("/dav/q3/a.csv")
    assert r.status_code == 401
    assert "WWW-Authenticate" in r.headers


def test_dav_cross_owner_403(tmp_path):
    client, store = _make_app(tmp_path)
    entry = store.provision("q3", "alice")
    store.set_credential(entry.token, "pw")
    store.write_file(entry.token, "a.csv", b"data")
    # TV-2: bob has no cache 'q3' of his own -> subject won't resolve for bob -> 401
    r = client.get("/dav/q3/a.csv", headers=_basic("bob", "pw"))
    assert r.status_code in (401, 403)  # no bytes leaked either way
    assert b"data" not in r.content


def test_dav_owner_full_cycle(tmp_path):
    client, store = _make_app(tmp_path)
    entry = store.provision("q3", "alice")
    store.set_credential(entry.token, "pw")
    h = _basic("alice", "pw")
    # PUT
    assert client.put("/dav/q3/a.csv", content=b"hello", headers=h).status_code == 201
    # GET
    g = client.get("/dav/q3/a.csv", headers=h)
    assert g.status_code == 200 and g.content == b"hello"
    # PROPFIND
    p = client.request("PROPFIND", "/dav/q3", headers={**h, "Depth": "1"})
    assert p.status_code == 207 and b"a.csv" in p.content
    # OPTIONS
    o = client.request("OPTIONS", "/dav/q3", headers=h)
    assert o.status_code == 200 and o.headers.get("DAV") == "1,2"
    # DELETE
    assert client.request("DELETE", "/dav/q3/a.csv", headers=h).status_code == 204


def test_dav_copy_same_subject(tmp_path):
    # COPY (rclone `copyto`) within one subject cache preserves the source.
    # Regression for integration bug 5.5: COPY was absent from DAV_METHODS
    # (rclone copyto -> 405) and the gateway-prefix mismatch mis-flagged the
    # Destination as cross_token.
    client, store = _make_app(tmp_path)
    entry = store.provision("q3", "alice")
    store.set_credential(entry.token, "pw")
    h = _basic("alice", "pw")
    assert client.put("/dav/q3/a.csv", content=b"x", headers=h).status_code == 201
    r = client.request("COPY", "/dav/q3/a.csv",
                       headers={**h, "Destination": "/dav/q3/b.csv"})
    assert r.status_code in (201, 204)
    # both source and copy exist
    assert client.get("/dav/q3/a.csv", headers=h).content == b"x"
    assert client.get("/dav/q3/b.csv", headers=h).content == b"x"
    # cross-subject COPY Destination -> 403
    x = client.request("COPY", "/dav/q3/a.csv",
                       headers={**h, "Destination": "/dav/OTHER/b.csv"})
    assert x.status_code == 403


def test_dav_propfind_empty_collection_visible(tmp_path):
    # Regression 5.5: an empty MKCOL dir must appear in PROPFIND (list_files
    # only sees files, so an empty collection was invisible -> false 404).
    client, store = _make_app(tmp_path)
    entry = store.provision("q3", "alice")
    store.set_credential(entry.token, "pw")
    h = _basic("alice", "pw")
    assert client.request("MKCOL", "/dav/q3/empty", headers=h).status_code == 201
    # PROPFIND the empty dir directly -> 207, not 404
    p = client.request("PROPFIND", "/dav/q3/empty", headers={**h, "Depth": "1"})
    assert p.status_code == 207
    # and it shows up as a child of root at Depth:1
    r = client.request("PROPFIND", "/dav/q3", headers={**h, "Depth": "1"})
    assert r.status_code == 207 and b"empty/" in r.content


# ── helpers ──
def _auth_header(user, pw):
    raw = base64.b64encode(f"{user}:{pw}".encode()).decode()
    return f"Basic {raw}"


_TMP_COUNTER = [0]


def _tmp():
    import tempfile
    d = tempfile.mkdtemp(prefix="pmdav_")
    return __import__("pathlib").Path(d)


# ── R14.4 path-traversal rejection (BR_20260706) ─────────────────────
def test_put_traversal_rejected_400():
    store = TokenStore(sessions_root=_tmp())
    entry = store.provision("q3", "alice")
    h = _dav.DavHandler(store, _dav.LockTable())
    status, _, body = h.handle(
        "PUT", token=entry.token, rel="../evil.txt", subject="q3",
        owner="alice", mount_prefix="/dav", base_href="/dav/q3/",
        body=b"pwn")
    assert status == 400
    assert b"STAGE_PATH_TRAVERSAL" in body
    # nothing escaped the token namespace
    assert not (entry.dir_path.parent / "evil.txt").exists()


def test_put_absolute_rel_rejected_400():
    store = TokenStore(sessions_root=_tmp())
    entry = store.provision("q3", "alice")
    h = _dav.DavHandler(store, _dav.LockTable())
    status, _, body = h.handle(
        "PUT", token=entry.token, rel="/etc/passwd", subject="q3",
        owner="alice", mount_prefix="/dav", base_href="/dav/q3/",
        body=b"pwn")
    assert status == 400
    assert b"STAGE_PATH_ABSOLUTE" in body


def test_delete_traversal_rejected_4xx(tmp_path):
    store = TokenStore(sessions_root=_tmp())
    entry = store.provision("q3", "alice")
    # plant a file OUTSIDE the token dir that traversal would target
    outside = entry.dir_path.parent / "victim.txt"
    outside.write_bytes(b"keep")
    h = _dav.DavHandler(store, _dav.LockTable())
    status, _, _ = h.handle(
        "DELETE", token=entry.token, rel="../victim.txt", subject="q3",
        owner="alice", mount_prefix="/dav", base_href="/dav/q3/")
    assert 400 <= status < 500
    assert outside.exists()          # victim untouched


def test_propfind_traversal_rejected_4xx(tmp_path):
    store = TokenStore(sessions_root=_tmp())
    entry = store.provision("q3", "alice")
    h = _dav.DavHandler(store, _dav.LockTable())
    status, _, _ = h.handle(
        "PROPFIND", token=entry.token, rel="../", subject="q3",
        owner="alice", mount_prefix="/dav", base_href="/dav/q3/",
        headers={"Depth": "1"})
    assert 400 <= status < 500
