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
import logging
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


def test_unusable_root_is_empty_but_NOT_silent(tmp_path, monkeypatch, caplog):
    """An absent root and a BROKEN root produce the same empty wire payload, so
    the log is the only thing that can tell them apart.

    Absent is legitimate ("this service ships no companion") and stays silent.
    A root that EXISTS but is not a readable directory — a mount that failed, a
    ``PATENTS_SKILLS_ROOT`` pointing at a file — is a deployment fault wearing
    the identical 200-with-empty-set face. Serving that silently is the same
    defect class as the 22-byte empty zip: success-shaped nothing.
    """
    broken = tmp_path / "root-is-a-file"
    broken.write_text("not a directory\n", encoding="utf-8")
    monkeypatch.setenv("PATENTS_SKILLS_ROOT", str(broken))
    with caplog.at_level(logging.WARNING, logger="patents_mcp.skills"):
        assert ss.list_shippable_skills() == []
    assert "not a readable directory" in caplog.text, (
        f"a broken mount was indistinguishable from 'no companion': {caplog.text!r}")

    caplog.clear()
    monkeypatch.setenv("PATENTS_SKILLS_ROOT", str(tmp_path / "genuinely-absent"))
    with caplog.at_level(logging.WARNING, logger="patents_mcp.skills"):
        assert ss.list_shippable_skills() == []
    assert caplog.text == "", f"an absent root is not a fault; stay quiet: {caplog.text!r}"


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
        # INSIDE the loop: this assertion used to sit after it, so it only ever
        # checked the LAST member — names=["/unsafe", "patentworks/SKILL.md"]
        # would have passed (BR_20260730 review F4).
        assert n.startswith("patentworks/"), f"member not rooted on skill name: {n}"


def test_zip_is_byte_stable():
    """Sorted member order -> identical bytes for an unchanged tree."""
    assert ss.pack_skill_zip("patentworks") == ss.pack_skill_zip("patentworks")


# ── review-driven regressions (BR_20260730 adversarial review) ───────
def test_every_listed_name_is_downloadable(tmp_path, monkeypatch):
    """F1 (MEDIUM): the LIST and the DOWNLOAD must share ONE admission gate.

    Listing used a bare ``is_dir()`` — which follows symlinks and applies no
    name rule — while downloading went through ``resolve_skill_dir``. So a
    symlinked or non-ASCII directory was advertised and then refused: the
    consumer contract "every name I list, you can fetch" was broken by the
    implementation itself.
    """
    root = tmp_path / "skills"
    outside = tmp_path / "outside"
    (outside).mkdir()
    (outside / "SKILL.md").write_text("leaked\n", encoding="utf-8")
    (root / "good").mkdir(parents=True)
    (root / "good" / "SKILL.md").write_text("ok\n", encoding="utf-8")
    (root / "\u4e2d\u6587").mkdir()          # non-ASCII: passes is_dir, fails safe-name
    (root / "\u4e2d\u6587" / "SKILL.md").write_text("x\n", encoding="utf-8")
    (root / "linkout").symlink_to(outside)   # symlink: passes is_dir, must be refused
    monkeypatch.setenv("PATENTS_SKILLS_ROOT", str(root))

    listed = [e["name"] for e in ss.list_shippable_skills()]
    assert listed == ["good"], f"advertised something it cannot serve: {listed}"
    for name in listed:
        ss.resolve_skill_dir(name)  # must not raise — that IS the contract


def test_symlinked_skill_dir_is_refused(tmp_path, monkeypatch):
    """A symlinked skill root is refused even when it points INSIDE the tree.

    The check runs on the un-resolved path on purpose: ``.resolve()`` erases the
    fact being tested, so the containment guard alone would wave this through.
    """
    root = tmp_path / "skills"
    (root / "real").mkdir(parents=True)
    (root / "real" / "SKILL.md").write_text("x\n", encoding="utf-8")
    (root / "alias").symlink_to(root / "real")   # inside the root, still refused
    monkeypatch.setenv("PATENTS_SKILLS_ROOT", str(root))

    assert [e["name"] for e in ss.list_shippable_skills()] == ["real"]
    with pytest.raises(ss.SkillShippingError) as e:
        ss.resolve_skill_dir("alias")
    assert e.value.code == "SKILL_NAME_INVALID"


def test_empty_skill_never_yields_200_empty_zip(tmp_path, monkeypatch):
    """F2 (LOW): a 22-byte end-of-central-directory record IS a valid zip.

    Served with 200 it reads to the consumer as success-with-nothing — the exact
    silent failure this BR exists to kill. Reached when a dir holds only
    dotfiles, or when the tree changes between the LIST and the DOWNLOAD.
    """
    root = tmp_path / "skills"
    (root / "dotonly").mkdir(parents=True)
    (root / "dotonly" / ".hidden.md").write_text("x\n", encoding="utf-8")
    (root / "empty").mkdir()
    (root / "vanishing").mkdir()
    (root / "vanishing" / "SKILL.md").write_text("x\n", encoding="utf-8")
    monkeypatch.setenv("PATENTS_SKILLS_ROOT", str(root))

    # advertised only while it has content...
    assert [e["name"] for e in ss.list_shippable_skills()] == ["vanishing"]
    # ...and the moment the content goes, the DOWNLOAD fails typed, not empty.
    (root / "vanishing" / "SKILL.md").unlink()
    for name in ("dotonly", "empty", "vanishing"):
        with pytest.raises(ss.SkillShippingError) as e:
            ss.pack_skill_zip(name)
        assert e.value.code == "SKILL_EMPTY", f"{name} -> {e.value.code}"


def test_errors_do_not_leak_filesystem_paths():
    """F5 (LOW): a remote client learns the name is bad/absent, not our layout.

    The 404 body used to carry ``looked in /app/skills``, disclosing the
    container's internal path to anyone probing the endpoint.
    """
    for bad in ("nosuch", "../etc", "\u4e2d\u6587"):
        with pytest.raises(ss.SkillShippingError) as e:
            ss.resolve_skill_dir(bad)
        assert "/" not in e.value.message, f"path leaked for {bad!r}: {e.value.message}"


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
    """Traversal is refused at SOME layer — this alone does not say which."""
    r = client.get(f"/skills/{attack}.zip")
    assert r.status_code in (400, 403, 404), f"traversal leaked: {r.status_code}"
    assert b"root:" not in r.content


def test_route_encoded_slash_is_stopped_by_the_ROUTER_not_the_guard(client):
    """F3 (LOW): pins WHICH layer refuses ``%2F``, because the distinction was
    being mis-reported as evidence that the in-handler guard had been exercised.

    Starlette decodes before matching, so an encoded slash becomes a real
    separator and the single-segment ``{name}`` simply fails to match — the
    request never reaches ``skill_zip``. Defence in depth is intact, but a probe
    like this tests the ROUTE TABLE, not ``resolve_skill_dir``. The body shape
    is the tell: the router's default 404 is plain text, ours is typed JSON.
    """
    r = client.get("/skills/..%2F..%2Fetc%2Fpasswd.zip")
    assert r.status_code == 404
    assert b"SKILL_" not in r.content, (
        "handler-typed body means the guard ran; this case must be refused "
        "EARLIER, by the router")


def test_route_reaches_the_in_handler_guard(client):
    """The complement: a name that DOES match the route but must fail the guard.

    Without this, no route-level test exercises ``resolve_skill_dir`` at all —
    the guard would be reachable only from unit tests while the HTTP surface
    went unverified.
    """
    r = client.get("/skills/\u4e2d\u6587.zip")   # single segment: matches, then guard rejects
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == "SKILL_NAME_INVALID", f"guard did not run: {body}"
    assert "/" not in body["detail"], f"path leaked: {body['detail']}"


def test_route_empty_skill_404_not_empty_zip(client, tmp_path, monkeypatch):
    """The HTTP face of F2: never 200 + a valid-but-empty archive."""
    root = tmp_path / "skills"
    (root / "hollow").mkdir(parents=True)
    (root / "hollow" / ".only-a-dotfile").write_text("x\n", encoding="utf-8")
    monkeypatch.setenv("PATENTS_SKILLS_ROOT", str(root))

    assert client.get("/skills").json()["skills"] == []
    r = client.get("/skills/hollow.zip")
    assert r.status_code == 404, f"served an empty archive with {r.status_code}"
    assert r.json()["code"] == "SKILL_EMPTY"


# ── VANS-driven regressions (validator ses_04c459f11, mutation survivors) ──
#
# Each test below exists because deleting the guard it covers left the suite
# ENTIRELY GREEN. A clause with an implementation anchor but no test anchor is
# one refactor away from silent removal — the exact shape of the original BR,
# where a green check coexisted with an absent guarantee.
def test_withheld_entries_are_announced_in_the_log(tmp_path, monkeypatch, caplog):
    """spec R4: a withheld entry is announced in the log — **never silently**.

    A directory that looks like a skill but cannot be served is an AUTHORING
    error: the operator has to learn about it, because the wire payload
    deliberately hides it (the consumer contract is "names I can download").
    Silence here means the author sees a skill on disk, no error anywhere, and
    no skill on the wire.

    Mutation that this pins (VANS MUT8): deleting both ``_log.warning`` calls
    left 28/28 green — no test in the suite observed logging at all
    (``grep -rln caplog tests/`` had zero hits repo-wide).
    """
    root = tmp_path / "skills"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "SKILL.md").write_text("leaked\n", encoding="utf-8")
    (root / "good").mkdir(parents=True)
    (root / "good" / "SKILL.md").write_text("ok\n", encoding="utf-8")
    (root / "\u4e2d\u6587").mkdir()                      # refused by the safe-name rule
    (root / "\u4e2d\u6587" / "SKILL.md").write_text("x\n", encoding="utf-8")
    (root / "linkout").symlink_to(outside)               # refused as an entry symlink
    (root / "hollow").mkdir()                            # refused as SKILL_EMPTY
    (root / "hollow" / ".dotfile-only").write_text("x\n", encoding="utf-8")
    monkeypatch.setenv("PATENTS_SKILLS_ROOT", str(root))

    with caplog.at_level(logging.WARNING, logger="patents_mcp.skills"):
        listed = [e["name"] for e in ss.list_shippable_skills()]

    assert listed == ["good"], f"advertised something it cannot serve: {listed}"
    for withheld in ("\u4e2d\u6587", "linkout", "hollow"):
        assert withheld in caplog.text, (
            f"{withheld!r} was withheld SILENTLY — the operator has no way to "
            f"discover the authoring error. Log was: {caplog.text!r}")
    assert "SKILL_EMPTY" in caplog.text, "the empty-skill reason must be named"


def test_containment_guard_fires_when_the_root_moves_mid_call(tmp_path, monkeypatch):
    """spec R4: a containment check on the RESOLVED path, independent of the
    name rule and the entry-symlink rule.

    Guard 3 is unreachable through the public API while guard 2 stands — on
    POSIX a non-symlink child cannot resolve out of its parent — so a naive
    fixture can never make it fire, and mutating it away looks free (VANS MUT6:
    ``if candidate.parent != root:`` -> ``if False:`` kept 28/28 green).

    What it actually defends is the TOCTOU between the two reads:
    ``resolve_skill_dir`` calls ``skills_root()`` TWICE (once resolved for the
    root, once unresolved to build the candidate). Re-point the root between
    those reads — a symlinked root swung by a deploy, or the env var rewritten
    — and the candidate lands in a tree the root no longer contains. That is
    the reachable case, so it is the one under test.
    """
    real = tmp_path / "real"
    (real / "good").mkdir(parents=True)
    (real / "good" / "SKILL.md").write_text("ok\n", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "good").mkdir(parents=True)
    (elsewhere / "good" / "SKILL.md").write_text("not ours to publish\n", encoding="utf-8")

    reads: list[int] = []

    def moving_root():
        reads.append(1)
        return real if len(reads) == 1 else elsewhere

    monkeypatch.setattr(ss, "skills_root", moving_root)

    with pytest.raises(ss.SkillShippingError) as e:
        ss.resolve_skill_dir("good")
    assert e.value.code == "SKILL_NAME_INVALID", (
        "a candidate outside the resolved root was accepted — the containment "
        "check is the only guard standing between here and an arbitrary tree")
    assert len(reads) >= 2, "fixture never exercised the two-read window"


def test_archive_never_carries_a_symlink_member(tmp_path, monkeypatch):
    """spec R4 / R9.7.1: no member of the archive is a symlink.

    A symlink inside a zip is a traversal primitive on EXTRACTION — the victim
    is the consumer, not this server, which is why no probe against this
    service can reveal it. ``is_file()`` alone follows the link and happily
    ships the target's bytes under an innocuous member name.

    Mutation that this pins (VANS MUT7): dropping ``p.is_symlink() or`` from
    ``_shippable_members`` left 28/28 green. It is the twin of the entry-symlink
    guard already covered by ``test_symlinked_skill_dir_is_refused`` — that one
    correctly went red under mutation, this one had no coverage at all.
    """
    root = tmp_path / "skills"
    secret = tmp_path / "secret.txt"
    secret.write_text("root:x:0:0:in-the-archive\n", encoding="utf-8")
    skill = root / "withlinks"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("ok\n", encoding="utf-8")
    (skill / "leak.txt").symlink_to(secret)              # follows out of the tree
    (skill / "self.md").symlink_to(skill / "SKILL.md")   # inside, still excluded
    monkeypatch.setenv("PATENTS_SKILLS_ROOT", str(root))

    names = zipfile.ZipFile(io.BytesIO(ss.pack_skill_zip("withlinks"))).namelist()
    assert names == ["withlinks/SKILL.md"], f"symlink member shipped: {names}"
    # and the advertised count must agree with what the archive really holds
    (listed,) = [e for e in ss.list_shippable_skills() if e["name"] == "withlinks"]
    assert listed["file_count"] == len(names)


def test_loose_bytecode_outside_pycache_is_excluded(tmp_path, monkeypatch):
    """spec R4: ``.pyc``/``.pyo`` are excluded — as a SUFFIX rule, not merely as
    a side effect of the ``__pycache__`` directory rule.

    ``test_zip_is_wellformed_and_hygienic`` asserts no bytecode ships, and it
    passes — but only because all 11 ``.pyc`` files in the real tree happen to
    live under ``__pycache__/``, where ``_EXCLUDED_DIRS`` catches them first.
    Deleting the suffix branch entirely kept that test green (VANS MUT5); it
    went red only after seeding a loose ``.pyc``. So the assertion was
    load-bearing by accident of the tree, and the rule under test was not the
    rule being exercised. This fixture makes the suffix rule the only thing
    standing between the file and the archive.
    """
    root = tmp_path / "skills"
    skill = root / "bytecode"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("ok\n", encoding="utf-8")
    (skill / "stray.pyc").write_bytes(b"\x00compiled\n")   # NOT under __pycache__
    (skill / "stray.pyo").write_bytes(b"\x00compiled\n")
    monkeypatch.setenv("PATENTS_SKILLS_ROOT", str(root))

    names = zipfile.ZipFile(io.BytesIO(ss.pack_skill_zip("bytecode"))).namelist()
    assert names == ["bytecode/SKILL.md"], f"compiled bytecode shipped: {names}"
    (listed,) = [e for e in ss.list_shippable_skills() if e["name"] == "bytecode"]
    assert listed["file_count"] == 1, f"count includes excluded bytecode: {listed}"
