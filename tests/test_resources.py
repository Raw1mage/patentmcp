"""R17.1(c) portable result retrieval — resources/list + resources/read.

plan patentmcp_r17-minimum-operational-toolset, tasks 1.3, TV-1..TV-4.
"""
import asyncio

import pytest

from patent_mcp_server import _resources as _res
from patent_mcp_server._token_store import TokenStore


@pytest.fixture()
def store(tmp_path):
    return TokenStore(sessions_root=tmp_path / "sessions")


# ── pure URI helpers ───────────────────────────────────────────────
def test_build_parse_roundtrip():
    uri = _res.build_uri("tok_ABC", "sub/dir/b.png")
    assert uri == "patent://tok_ABC/sub/dir/b.png"
    token, rel = _res.parse_uri(uri)
    assert (token, rel) == ("tok_ABC", "sub/dir/b.png")


def test_parse_rejects_wrong_scheme():
    with pytest.raises(ValueError):
        _res.parse_uri("file:///etc/passwd")


def test_parse_rejects_missing_rel():
    with pytest.raises(ValueError):
        _res.parse_uri("patent://tok_ABC")
    with pytest.raises(ValueError):
        _res.parse_uri("patent://tok_ABC/")


def test_parse_encodes_special_chars():
    # a rel segment with a reserved char round-trips
    uri = _res.build_uri("tok_X", "a b?.csv")
    token, rel = _res.parse_uri(uri)
    assert (token, rel) == ("tok_X", "a b?.csv")


# ── TV-1: exact bytes ──────────────────────────────────────────────
def test_read_returns_exact_bytes(store):
    entry = store.put_bytes(b"PDF-BYTES-123", "spec.pdf")
    uri = _res.build_uri(entry.token, "spec.pdf")
    assert _res.read_resource_bytes(store, uri) == b"PDF-BYTES-123"


# ── TV-2: unknown token/rel fails loud ─────────────────────────────
def test_read_unknown_token_fails_loud(store):
    with pytest.raises(Exception):
        _res.read_resource_bytes(store, "patent://tok_DOESNOTEXIST/x.pdf")


def test_read_missing_rel_fails_loud(store):
    entry = store.put_bytes(b"x", "a.pdf")
    with pytest.raises(Exception):
        _res.read_resource_bytes(store, _res.build_uri(entry.token, "missing.pdf"))


# ── TV-3: traversal rejected ───────────────────────────────────────
def test_read_traversal_rejected(store):
    entry = store.put_bytes(b"x", "a.pdf")
    # ../../etc/passwd escapes the token namespace -> StagingError/TokenNotFound
    with pytest.raises(Exception):
        _res.read_resource_bytes(store, f"patent://{entry.token}/../../etc/passwd")


# ── TV-4: list mirrors the live store ──────────────────────────────
def test_list_mirrors_store(store):
    e1 = store.put_bytes(b"aaa", "a.csv")
    e2 = store.put_bytes(b"bbb", "b.png")
    descs = _res.list_resource_descriptors(store)
    uris = {d["uri"] for d in descs}
    assert _res.build_uri(e1.token, "a.csv") in uris
    assert _res.build_uri(e2.token, "b.png") in uris
    # each descriptor carries name + mime + size
    for d in descs:
        assert d["name"] and d["mime_type"] and d["size"] is not None


def test_list_empty_store_is_empty(store):
    assert _res.list_resource_descriptors(store) == []


# ── integration: FastMCP template read + dynamic list ──────────────
def test_fastmcp_resource_face_end_to_end(monkeypatch, tmp_path):
    import os
    from patent_mcp_server import patents

    # produce an artifact in the server's live token store
    entry = patents.token_store.put_bytes(b"HELLO-RESOURCE", "greeting.txt")
    uri = _res.build_uri(entry.token, "greeting.txt")

    async def _run():
        # resources/list mirrors the store
        resources = await patents.mcp.list_resources()
        assert any(str(r.uri) == uri for r in resources)
        # resources/read returns exact bytes via the template
        contents = await patents.mcp.read_resource(uri)
        chunk = list(contents)[0]
        data = chunk.content
        if isinstance(data, str):
            data = data.encode()
        assert data == b"HELLO-RESOURCE"

    asyncio.run(_run())

    # unknown resource fails loud
    async def _run_unknown():
        with pytest.raises(Exception):
            await patents.mcp.read_resource("patent://tok_NOPE/x.txt")

    asyncio.run(_run_unknown())
