"""R17.6 end-to-end conformance eval — Minimum Operational Toolset + Host Mediation.

plan patentmcp_r17-minimum-operational-toolset, task 4.2, TV-10/TV-11.

Exercises the full host-mediation chain twice:
  * TV-10 portable floor : host bytes -> ingress -> token -> transform
                           -> assertion-backed QA -> resources/read egress
                           (NO WebDAV — R0/R2 portable floor only)
  * TV-11 WebDAV floor   : same chain, egress via cache_export with content
                           assertions (host-visible extension), empty refused
"""
import asyncio

import pytest

from patent_mcp_server import _delivery
from patent_mcp_server import _resources as _res
from patent_mcp_server._token_store import TokenStore


@pytest.fixture()
def store(tmp_path):
    return TokenStore(sessions_root=tmp_path / "sessions")


def _cache_export(**kwargs):
    from patent_mcp_server import patents
    tool = patents.mcp._tool_manager._tools["cache_export"]
    return asyncio.run(tool.fn(**kwargs))


# ── TV-10: portable floor (no WebDAV) ──────────────────────────────
def test_r17_6_portable_floor_no_webdav(store):
    # host file -> ingress (bytes land in a token namespace)
    host_bytes = b"col_a,col_b\n1,2\n3,4\n"
    entry = store.put_bytes(host_bytes, "screening.csv")

    # transform: derive a second artifact in the same namespace
    derived = b"summary: 2 rows\n"
    store.write_file(entry.token, "summary.txt", derived)

    # assertion-backed QA before we call it delivery-ready
    files = [{"rel": f["rel"], "size": f["size"]} for f in store.list_files(entry.token)]
    qa = _delivery.preflight_export(
        files, assert_min_files=2, assert_nonempty=True,
        assert_contains_rel=["screening.csv", "summary.txt"])
    assert qa["ok"] is True, f"QA must pass on a real deliverable: {qa}"

    # egress via resources/read ONLY (portable floor, no WebDAV)
    uri_csv = _res.build_uri(entry.token, "screening.csv")
    uri_sum = _res.build_uri(entry.token, "summary.txt")
    assert _res.read_resource_bytes(store, uri_csv) == host_bytes
    assert _res.read_resource_bytes(store, uri_sum) == derived

    # resources/list mirrors the store — both artifacts discoverable
    uris = {d["uri"] for d in _res.list_resource_descriptors(store)}
    assert uri_csv in uris and uri_sum in uris


# ── TV-11: WebDAV floor (host-visible egress) ──────────────────────
def test_r17_6_webdav_floor_with_assertions(tmp_path, monkeypatch):
    from patent_mcp_server import patents
    store = TokenStore(sessions_root=tmp_path / "sessions")
    monkeypatch.setattr(patents, "token_store", store)

    # host file -> ingress -> token
    entry = store.provision("subjE2E", "ownerO")
    store.write_file(entry.token, "rep.csv", b"a,b\n1,2\n")
    store.write_file(entry.token, "fig.png", b"\x89PNG\r\n\x1a\n")

    # empty-tree guard is real: a sibling empty subject is refused
    empty = store.provision("subjEmpty", "ownerO")
    empty_target = tmp_path / "empty_out"
    empty_target.parent.mkdir(parents=True, exist_ok=True)
    empty_res = _cache_export(
        subject_id="subjEmpty", target=str(empty_target), owner_identity="ownerO")
    assert empty_res["success"] is False
    assert empty_res["error_code"] == "EXPORT_EMPTY"

    # egress via cache_export WITH content assertions
    target = tmp_path / "deliver" / "landing"
    target.parent.mkdir(parents=True, exist_ok=True)
    res = _cache_export(
        subject_id="subjE2E", target=str(target), owner_identity="ownerO",
        assert_nonempty=True, assert_min_files=2,
        assert_contains_rel=["rep.csv", "fig.png"])
    assert res["success"] is True, res
    assert res["files_copied"] == 2
    assert (target / "rep.csv").read_bytes() == b"a,b\n1,2\n"
    assert (target / "fig.png").read_bytes() == b"\x89PNG\r\n\x1a\n"
