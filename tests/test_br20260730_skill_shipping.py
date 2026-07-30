"""BR_20260730 — R9.2 skill shipping needs BOTH halves: list AND download.

Before this BR the route table carried exactly one ``/skills*`` entry, with the
skill name f-string'd into the pattern::

    Route(f"/skills/{_SKILL_NAME}.zip", skill_zip, methods=["GET"])

The zip served fine, so every static conformance check stayed green — but a
generic R9.2 consumer does *list → download by name* and got a 404 at step one,
indistinguishable from "this service ships no companion skill". The skill was
reachable only by a client that already knew the magic name ``patentworks``.

These tests pin BOTH halves plus the traversal guards that a parameterised
``{name}`` route makes newly reachable.
"""
from __future__ import annotations

import io
import os
import zipfile

import pytest

os.environ.setdefault("PATENTS_SKILLS_ROOT", "skills")

from patent_mcp_server import _skill_shipping as ss


# ── unit: the shipping module (no server) ────────────────────────────
def test_list_returns_bare_names_not_filenames():
    """R9.2 elements MUST be bare skill NAMES.

    Serving filenames here (``patentworks.zip``) is the documented bodesign
    anti-pattern: the consumer concatenates ``<name>.zip`` and asks for
    ``patentworks.zip.zip``.
    """
    skills = ss.list_shippable_skills()
    names = [s["name"] for s in skills]
    assert "patentworks" in names, f"companion skill must be listed: {skills}"
    for n in names:
        assert not n.endswith(".zip"), f"listed a FILENAME, not a bare name: {n!r}"
        assert "/" not in n and "\\" not in n, f"name must be one segment: {n!r}"
    for s in skills:
        assert s["file_count"] > 0, f"an empty skill must not be advertised: {s}"


def test_list_is_generic_not_hardcoded(tmp_path, monkeypatch):
    """A second companion must become discoverable by dropping a directory in —
    the F2 half of the BR (route hard-coded a single name, so a new skill would
    have required a code change)."""
    root = tmp_path / "skills"
    (root / "alpha").mkdir(parents=True)
    (root / "alpha" / "SKILL.md").write_text("# alpha\n", encoding="utf-8")
    (root / "beta" / "sub").mkdir(parents=True)
    (root / "beta" / "sub" / "ref.md").write_text("x\n", encoding="utf-8")
    (root / "empty").mkdir()  # ships nothing -> must NOT be advertised
    monkeypatch.setenv("PATENTS_SKILLS_ROOT", str(root))

    assert [s["name"] for s in ss.list_shippable_skills()] == ["alpha", "beta"]


def test_list_empty_root_is_honest_empty(tmp_path, monkeypatch):
    """No tree -> ``[]``, not a raise. The route must still answer 200 so the
    consumer reads an honest "no companion" instead of a transport error."""
    monkeypatch.setenv("PATENTS_SKILLS_ROOT", str(tmp_path / "nope"))
    assert ss.list_shippable_skills() == []


@pytest.mark.parametrize("bad", ["../bin", "..", ".", "a/b", "", "foo/../../etc",
                                 "../../../../etc/passwd", "foo\x00bar"])
def test_traversal_names_rejected(bad):
    """Guard 1 (safe-name regex) or guard 2 (containment) must reject every
    escape attempt — a parameterised route makes these newly reachable."""
    with pytest.raises(ss.SkillShippingError) as e:
        ss.resolve_skill_dir(bad)
    assert e.value.code == "SKILL_NAME_INVALID", f"{bad!r} -> {e.value.code}"


def test_unknown_name_is_typed_not_found():
    """Well-formed but absent -> typed SKILL_NOT_FOUND (route → 404), never a
    200 carrying an empty archive."""
    with pytest.raises(ss.SkillShippingError) as e:
        ss.resolve_skill_dir("no-such-skill")
    assert e.value.code == "SKILL_NOT_FOUND"


def test_zip_is_wellformed_and_hygienic():
    """R9.7.1 producer hygiene: no absolute paths, no ``..`` segments, no
    compiled bytecode (``.pyc`` leaks absolute build paths via co_filename)."""
    data = ss.pack_skill_zip("patentworks")
    assert len(data) > 0
    zf = zipfile.ZipFile(io.BytesIO(data))
    assert zf.testzip() is None, "archive must not be corrupt"
    names = zf.namelist()
    assert names, "archive must not be empty"
    assert "patentworks/SKILL.md" in names, f"missing entrypoint: {names[:5]}"
    for n in names:
        assert not n.startswith("/"), f"absolute path in archive: {n}"
        assert ".." not in n.split("/"), f"dot-dot segment in archive: {n}"
        assert not n.endswith((".pyc", ".pyo")), f"compiled bytecode shipped: {n}"
        assert "__pycache__" not in n.split("/"), f"pycache shipped: {n}"
    assert n.startswith("patentworks/")  # rooted on the skill name, unzips in place


def test_zip_is_byte_stable():
    """Sorted member order -> identical bytes for an unchanged tree."""
    assert ss.pack_skill_zip("patentworks") == ss.pack_skill_zip("patentworks")


# ── route-level: both halves over the real ASGI app ──────────────────
@pytest.fixture()
def client(tmp_path):
    from starlette.testclient import TestClient
    from patent_mcp_server._http_app import build_app
    from patent_mcp_server._token_store import TokenStore
    from patent_mcp_server import patents

    app = build_app(patents.mcp, TokenStore(sessions_root=tmp_path / "sessions"))
    return TestClient(app)


def test_route_bare_list_exists(client):
    """THE BR: bare ``GET /skills`` used to 404. It must now list the companion."""
    r = client.get("/skills")
    assert r.status_code == 200, f"bare GET /skills must exist (BR_20260730): {r.status_code}"
    body = r.json()
    assert body["ok"] is True
    assert "patentworks" in [s["name"] for s in body["skills"]]
    assert body["count"] == len(body["skills"])


def test_route_download_still_works(client):
    """Regression: the half that already worked (200 / ~200KB) must keep working."""
    r = client.get("/skills/patentworks.zip")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert "patentworks.zip" in r.headers.get("content-disposition", "")
    assert len(r.content) > 0
    assert zipfile.ZipFile(io.BytesIO(r.content)).testzip() is None


def test_route_list_then_download_end_to_end(client):
    """The generic R9.2 consumer flow, which is what actually broke: discover a
    name with no prior knowledge, then fetch that exact name."""
    for s in client.get("/skills").json()["skills"]:
        r = client.get(f"/skills/{s['name']}.zip")
        assert r.status_code == 200, f"listed {s['name']!r} but download failed"
        assert len(zipfile.ZipFile(io.BytesIO(r.content)).namelist()) == s["file_count"]


def test_route_unknown_name_404_not_500(client):
    r = client.get("/skills/no-such-skill.zip")
    assert r.status_code == 404
    assert r.json()["code"] == "SKILL_NOT_FOUND"


@pytest.mark.parametrize("attack", ["..%2F..%2Fetc%2Fpasswd", "..", "%2e%2e%2fbin"])
def test_route_traversal_rejected(client, attack):
    r = client.get(f"/skills/{attack}.zip")
    assert r.status_code in (400, 403, 404), f"traversal leaked: {r.status_code}"
    assert b"root:" not in r.content
