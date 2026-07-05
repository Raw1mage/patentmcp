"""cache_* MCP tool tests (group 5): provision idempotent (TV-1), owner-required
no-fallback, export unreachable 502 (TV-5), dirty close 409 (TV-4), force close."""
from __future__ import annotations

import asyncio

import pytest

from patent_mcp_server._token_store import TokenStore


@pytest.fixture()
def patched_store(tmp_path, monkeypatch):
    """Point patents.token_store at a fresh temp store for isolated tool tests."""
    import patent_mcp_server.patents as P
    store = TokenStore(sessions_root=tmp_path)
    monkeypatch.setattr(P, "token_store", store)
    return P, store


def _run(coro):
    return asyncio.run(coro)


def test_provision_idempotent_same_token(patched_store):
    P, store = patched_store
    r1 = _run(P.cache_provision("q3", "alice"))
    r2 = _run(P.cache_provision("q3", "alice"))
    assert r1["success"] and r2["success"]
    assert r1["token"] == r2["token"]                 # TV-1: same token
    assert "credential" in r1                          # first provision -> credential
    assert "credential" not in r2                      # re-provision -> no re-leak
    assert r1["mount_path"] == "/dav/q3"


def test_provision_requires_owner(patched_store):
    P, _ = patched_store
    r = _run(P.cache_provision("q3", ""))
    assert r["success"] is False and r["error_code"] == "OWNER_REQUIRED"


def test_cache_list_only_own(patched_store):
    P, store = patched_store
    _run(P.cache_provision("q3", "alice"))
    _run(P.cache_provision("q4", "bob"))
    r = _run(P.cache_list("alice"))
    assert r["success"] and r["count"] == 1
    assert r["caches"][0]["subject_id"] == "q3"


def test_export_target_unreachable_502(patched_store):
    P, store = patched_store
    _run(P.cache_provision("q3", "alice"))
    r = _run(P.cache_export("q3", "/nonexistent/dir/out", "alice"))
    assert r["success"] is False
    assert r["error_code"] == "EXPORT_TARGET_UNREACHABLE"   # TV-5


def test_export_then_dirty_close_409(patched_store, tmp_path):
    P, store = patched_store
    prov = _run(P.cache_provision("q3", "alice"))
    token = prov["token"]
    store.write_file(token, "a.csv", b"one")
    # export to a reachable target
    tgt = tmp_path / "landing" / "q3"
    (tmp_path / "landing").mkdir()
    ex = _run(P.cache_export("q3", str(tgt), "alice"))
    assert ex["success"] and ex["files_copied"] == 1
    # now mutate -> dirty
    store.write_file(token, "b.csv", b"two")
    close = _run(P.cache_close("q3", "alice"))
    assert close["success"] is False                        # TV-4
    assert close["error_code"] == "WORKSPACE_CLOSE_DIRTY"
    assert "b.csv" in close["unlanded"]
    # force close reaps
    forced = _run(P.cache_close("q3", "alice", force=True))
    assert forced["success"] and forced["reaped"]
    assert store.find_by_subject("alice", "q3") is None


def test_clean_close_reaps(patched_store, tmp_path):
    P, store = patched_store
    prov = _run(P.cache_provision("q3", "alice"))
    token = prov["token"]
    store.write_file(token, "a.csv", b"one")
    (tmp_path / "land").mkdir()
    _run(P.cache_export("q3", str(tmp_path / "land" / "q3"), "alice"))
    # no further edits -> clean
    close = _run(P.cache_close("q3", "alice"))
    assert close["success"] and close["reaped"]


def test_export_missing_cache(patched_store, tmp_path):
    P, _ = patched_store
    (tmp_path / "x").mkdir()
    r = _run(P.cache_export("nope", str(tmp_path / "x" / "o"), "alice"))
    assert r["success"] is False and r["error_code"] == "CACHE_NOT_FOUND"


# ── R14.6 MCP-rail credential issuance (BR_20260706) ──────────────────
def test_issue_webdav_credential_rotates(patched_store):
    P, store = patched_store
    r1 = _run(P.cache_provision("q3", "alice"))
    c1 = r1["credential"]
    token = r1["token"]
    # re-provision with the flag -> mint/rotate, cleartext returned again
    r2 = _run(P.cache_provision("q3", "alice", issue_webdav_credential=True))
    assert r2["success"] and r2["token"] == token
    c2 = r2["credential"]
    assert c2 != c1
    # old credential invalidated, new one verifies (rotation semantics)
    assert store.verify_credential(token, c1) is False
    assert store.verify_credential(token, c2) is True


def test_default_payload_byte_identical_without_flag(patched_store):
    P, _ = patched_store
    r1 = _run(P.cache_provision("q3", "alice"))
    # first provision: credential minted exactly once
    assert set(r1.keys()) == {"success", "token", "subject_id",
                              "owner_identity", "mount_path", "credential"}
    # re-provision WITHOUT the flag: pre-BR payload, no extra fields, no re-leak
    r2 = _run(P.cache_provision("q3", "alice"))
    assert r2 == {
        "success": True,
        "token": r1["token"],
        "subject_id": "q3",
        "owner_identity": "alice",
        "mount_path": "/dav/q3",
    }


def test_issue_flag_still_requires_owner(patched_store):
    P, _ = patched_store
    r = _run(P.cache_provision("q3", "", issue_webdav_credential=True))
    assert r["success"] is False and r["error_code"] == "OWNER_REQUIRED"
