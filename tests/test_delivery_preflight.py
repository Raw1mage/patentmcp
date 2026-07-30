"""R17.2.4/5 typed asset preflight + content assertions (cache_export delivery gate).

plan patentmcp_r17-minimum-operational-toolset, tasks 3.3, TV-7/8/9.
"""
import asyncio

import pytest

from patent_mcp_server import _delivery


# ── pure preflight helper ──────────────────────────────────────────
def test_preflight_empty_refused():
    v = _delivery.preflight_export([])
    assert v["ok"] is False
    assert v["error_code"] == "EXPORT_EMPTY"


def test_preflight_nonempty_passes_by_default():
    v = _delivery.preflight_export([{"rel": "a.csv", "size": 10}])
    assert v["ok"] is True


def test_preflight_assert_nonempty_fails_on_zero_length():
    v = _delivery.preflight_export(
        [{"rel": "a.csv", "size": 0}], assert_nonempty=True
    )
    assert v["ok"] is False and v["error_code"] == "ASSERTION_FAILED"


def test_preflight_assert_min_files():
    files = [{"rel": "a.csv", "size": 5}]
    assert _delivery.preflight_export(files, assert_min_files=2)["ok"] is False
    files2 = [{"rel": "a.csv", "size": 5}, {"rel": "b.csv", "size": 5}]
    assert _delivery.preflight_export(files2, assert_min_files=2)["ok"] is True


def test_preflight_assert_contains_rel():
    files = [{"rel": "a.csv", "size": 5}]
    v = _delivery.preflight_export(files, assert_contains_rel=["a.csv", "b.csv"])
    assert v["ok"] is False and "b.csv" in str(v["failed"])
    v2 = _delivery.preflight_export(files, assert_contains_rel=["a.csv"])
    assert v2["ok"] is True


def test_preflight_no_assertions_is_backward_compat():
    # no assertion kwargs => only the empty gate applies (byte-identical behaviour)
    files = [{"rel": "x", "size": 1}]
    assert _delivery.preflight_export(files) == {"ok": True}


def test_extract_assertions_drops_none():
    kwargs = {"assert_nonempty": None, "assert_min_files": 2, "other": 1}
    assert _delivery.extract_assertions(kwargs) == {"assert_min_files": 2}


# ── cache_export end-to-end ────────────────────────────────────────
def _cache_export(**kwargs):
    """Invoke the registered cache_export coroutine via the tool manager
    (the module-level name is wrapped by friction_tool and loses .fn)."""
    from patent_mcp_server import patents
    tool = patents.mcp._tool_manager._tools["cache_export"]
    return asyncio.run(tool.fn(**kwargs))


@pytest.fixture()
def isolated_store(tmp_path, monkeypatch):
    from patent_mcp_server._token_store import TokenStore
    from patent_mcp_server import patents
    store = TokenStore(sessions_root=tmp_path / "sessions")
    monkeypatch.setattr(patents, "token_store", store)
    return store


# TV-7: empty export refused, nothing landed
def test_cache_export_empty_refused(isolated_store, tmp_path, monkeypatch):
    from patent_mcp_server import patents
    store = isolated_store
    entry = store.provision("subjX", "ownerO")
    target = tmp_path / "out" / "landing"
    target.parent.mkdir(parents=True)

    res = _cache_export(
        subject_id="subjX", target=str(target), owner_identity="ownerO")
    assert res["success"] is False
    assert res["error_code"] == "EXPORT_EMPTY"
    # nothing landed
    assert not target.exists() or not any(target.iterdir())


# TV-8: assertion failure typed, nothing landed
def test_cache_export_assertion_failed(isolated_store, tmp_path):
    from patent_mcp_server import patents
    store = isolated_store
    entry = store.provision("subjA", "ownerO")
    store.write_file(entry.token, "only.csv", b"data")
    target = tmp_path / "out2" / "landing"
    target.parent.mkdir(parents=True)

    res = _cache_export(
        subject_id="subjA", target=str(target), owner_identity="ownerO",
        assert_min_files=2)
    assert res["success"] is False
    assert res["error_code"] == "ASSERTION_FAILED"


# TV-9: no assertions, non-empty tree lands as before
def test_cache_export_backward_compat_lands(isolated_store, tmp_path):
    from patent_mcp_server import patents
    store = isolated_store
    entry = store.provision("subjB", "ownerO")
    store.write_file(entry.token, "a.csv", b"aaa")
    store.write_file(entry.token, "b.csv", b"bbb")
    target = tmp_path / "out3" / "landing"
    target.parent.mkdir(parents=True)

    res = _cache_export(
        subject_id="subjB", target=str(target), owner_identity="ownerO")
    assert res["success"] is True
    assert res["files_copied"] == 2
    assert (target / "a.csv").read_bytes() == b"aaa"


# assertion PASS path lands
def test_cache_export_assertion_pass_lands(isolated_store, tmp_path):
    from patent_mcp_server import patents
    store = isolated_store
    entry = store.provision("subjC", "ownerO")
    store.write_file(entry.token, "rep.csv", b"content")
    target = tmp_path / "out4" / "landing"
    target.parent.mkdir(parents=True)

    res = _cache_export(
        subject_id="subjC", target=str(target), owner_identity="ownerO",
        assert_nonempty=True, assert_min_files=1, assert_contains_rel=["rep.csv"])
    assert res["success"] is True
    assert res["files_copied"] == 1
