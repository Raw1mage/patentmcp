"""R9 skill-shipping remote half — companion-skill list + zip download.

owning spec: ``specs/patentmcp/mcp-standard-conformance/`` (this repo), which
tracks ``specs/mcp-integration-standard/`` (opencode repo):

    R9.2  ``GET /skills``            — companion-skill LIST (bare skill names)
    R9.2  ``GET /skills/<name>.zip`` — remote download, per name
    R9.7.1 producer hygiene          — no absolute paths / ``..`` / symlinks
                                       inside the archive

Why this module exists (BR_20260730)
====================================

R9 is two halves serving different clients:

* ``mcp.json.skillPaths`` — in-repo discovery. An opencode host with a local
  ``appRoot`` resolves the relative path itself.
* the HTTP surface — remote discovery + download. A client reaching this server
  over the socket has NO ``appRoot``, so ``skillPaths`` is unresolvable for it.

patentmcp shipped only ``/skills/patentworks.zip`` — the DOWNLOAD half, with the
skill name baked into the route pattern via an f-string. The zip served fine
(200 / ~200KB), but a generic R9.2 consumer does *list → download by name* and
died at step one with a 404 that is indistinguishable from "this service ships
no skill". That is the BR_20260730 failure shape: the skill was reachable only
by a client that already knew the magic name.

This module is the generic replacement: it enumerates ``skills/`` as data, so a
second companion skill becomes discoverable by dropping a directory in — no code
change. Kept standalone (no Starlette import) so the whole contract, traversal
rejection included, is unit-testable without building the ASGI app.
"""

from __future__ import annotations

import io
import logging
import os
import re
import zipfile
from pathlib import Path

_log = logging.getLogger("patents_mcp.skills")

__all__ = [
    "SkillShippingError",
    "skills_root",
    "list_shippable_skills",
    "resolve_skill_dir",
    "pack_skill_zip",
]

# A skill name is ONE path segment: letters/digits/dot/underscore/hyphen. No
# slash, no ``..``, no absolute marker — the FIRST traversal guard, applied
# before the name ever touches the filesystem. ``resolve_skill_dir`` adds a
# SECOND containment check, so the two are defence in depth.
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

# Never ship compiled bytecode or editor/VCS residue: it is interpreter- and
# arch-specific junk that bloats the archive and can leak absolute source paths
# in ``co_filename`` (R9.7.1 hygiene).
_EXCLUDED_DIRS = {"__pycache__", ".git", ".svn", "node_modules"}
_EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


class SkillShippingError(Exception):
    """Typed failure so routes map to a precise HTTP status, never a 500.

    ``code`` values:
      * ``SKILL_NAME_INVALID`` — fails the safe-name rule or the containment
        check (i.e. a traversal attempt). Route → 404 (we deliberately do not
        distinguish "malformed" from "absent" to a remote caller).
      * ``SKILL_NOT_FOUND``    — well-formed name, no such skill directory.
        Route → 404.
      * ``SKILL_EMPTY``        — the directory exists but holds nothing
        shippable (only dotfiles / bytecode), or the tree changed between the
        LIST and the DOWNLOAD. Route → 404. This code exists so "never a 200
        carrying an empty archive" is enforced by the type system instead of by
        hoping the directory is non-empty (review F2: a 22-byte empty zip was
        being served with 200).

    Messages deliberately carry NO filesystem paths: a remote client learns only
    that the name is bad or absent, never the container's layout. Full detail
    (including the root) goes to the server log instead (review F5).
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def skills_root() -> Path:
    """The shippable-skills SSOT tree.

    ``PATENTS_SKILLS_ROOT`` wins when set (container images mount the tree at a
    different path than the repo layout); otherwise derive from this file's
    location — ``…/<repo>/src/patent_mcp_server/_skill_shipping.py`` sits four
    parents below the repo root when vendored, matching the historical
    ``_http_app._skills_root`` derivation this module supersedes.
    """
    env = os.environ.get("PATENTS_SKILLS_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[4] / "skills"


def _shippable_members(skill_dir: Path) -> list[Path]:
    """Every file that belongs in the archive, sorted for byte-stable output.

    Excluded: dotfiles/dotdirs, ``__pycache__`` & friends, ``.pyc``/``.pyo``,
    and SYMLINKS (R9.7.1 — a symlink in an archive is a traversal primitive on
    extraction, and ``is_file()`` alone would happily follow one out of tree).
    """
    out: list[Path] = []
    for p in sorted(skill_dir.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        parts = p.relative_to(skill_dir).parts
        if any(part.startswith(".") for part in parts):
            continue
        if any(part in _EXCLUDED_DIRS for part in parts):
            continue
        if p.suffix in _EXCLUDED_SUFFIXES:
            continue
        out.append(p)
    return out


def list_shippable_skills() -> list[dict[str, object]]:
    """Enumerate every shippable skill as ``{name, file_count}``.

    Generic by construction — reads the directory, hard-codes no skill name. A
    skill is any immediate subdirectory of :func:`skills_root` holding at least
    one shippable file (an empty dir ships nothing, so it is not advertised).
    ``file_count`` lets a caller sanity-check the zip it later downloads.

    A missing/unreadable root yields ``[]`` rather than raising: the LIST route
    must still answer 200 with an honest empty set (the consumer treats that as
    "no companion", which is then true).
    """
    root = skills_root()
    out: list[dict[str, object]] = []
    if not root.is_dir():
        # Absent root is a legitimate "no companion" (silent). But a root that
        # EXISTS and is merely unreadable/not-a-directory is a deployment fault
        # wearing the same 200-with-empty-set face — indistinguishable on the
        # wire from a service that genuinely ships nothing. Same anti-silence
        # clause the withheld-entry warnings serve: the operator must be able to
        # tell a misconfiguration from an honest empty (VANS gap, BR_20260730).
        if root.exists():
            _log.warning(
                "[skills] skills root %s exists but is not a readable directory "
                "— serving an EMPTY list; check the mount and PATENTS_SKILLS_ROOT",
                root)
        return out
    for entry in sorted(root.iterdir()):
        # Admission through the SAME gate the download path uses, so any name
        # appearing here is guaranteed to survive resolve_skill_dir() later.
        try:
            skill_dir = resolve_skill_dir(entry.name)
        except SkillShippingError as e:
            # NOT silent: a directory that looks like a skill but cannot be
            # served is an authoring mistake the operator must see. It stays out
            # of the wire payload (the consumer contract is "names I can
            # download") but is announced in the log (review F1).
            if entry.is_dir() or entry.is_symlink():
                _log.warning("[skills] not advertising %r under %s: %s (%s)",
                             entry.name, root, e.code, e.message)
            continue
        members = _shippable_members(skill_dir)
        if not members:
            _log.warning(
                "[skills] not advertising %r under %s: SKILL_EMPTY (no shippable "
                "file — only dotfiles/bytecode?)", entry.name, root)
            continue
        out.append({"name": entry.name, "file_count": len(members)})
    return out


def resolve_skill_dir(name: str) -> Path:
    """Validate ``name`` and return the contained skill directory.

    THE single admission gate. :func:`list_shippable_skills` and
    :func:`pack_skill_zip` BOTH go through here, which is what makes "every
    listed name is downloadable" a structural guarantee rather than two
    rule-sets that happen to agree. Before the BR_20260730 review they did not
    agree: listing used a bare ``is_dir()`` — which follows symlinks and applies
    no name rule — so a symlinked or non-ASCII directory was advertised and then
    rejected on download, a 200-then-404 contradiction (review F1).

    Three independent guards:
      1. ``name`` matches the safe-name rule (single segment, no slash / ``..``
         / absolute marker). ``../bin`` or ``a/b`` never passes.
      2. The entry must not itself be a SYMLINK. Tested on the UN-resolved path,
         because ``.resolve()`` erases the very fact being tested; guard 3 alone
         would wave through a symlink pointing back INSIDE the root.
      3. After ``.resolve()`` the candidate must still be a DIRECT child of the
         resolved skills root — catches what the regex might miss (escape via a
         symlinked parent, unicode trickery, the root itself).

    Raises :class:`SkillShippingError` (``SKILL_NAME_INVALID`` /
    ``SKILL_NOT_FOUND``); callers map both to 404.
    """
    if not isinstance(name, str) or not name or name in (".", ".."):
        raise SkillShippingError(
            "SKILL_NAME_INVALID", "skill name must be a single path segment")
    if not _SAFE_NAME_RE.match(name):
        raise SkillShippingError(
            "SKILL_NAME_INVALID",
            "skill name contains characters outside [A-Za-z0-9._-] "
            "(no slash, no '..', no path separator — this is a traversal guard)",
        )
    root = skills_root().resolve()
    unresolved = skills_root() / name
    if unresolved.is_symlink():
        raise SkillShippingError(
            "SKILL_NAME_INVALID",
            "skill entry is a symlink (refused: it can point outside the tree, "
            "and its target is not ours to publish)",
        )
    candidate = unresolved.resolve()
    if candidate.parent != root:
        raise SkillShippingError(
            "SKILL_NAME_INVALID",
            "skill name does not resolve to a direct child of the skills root "
            "(traversal rejected)",
        )
    if not candidate.is_dir():
        raise SkillShippingError("SKILL_NOT_FOUND", "no such shippable skill")
    return candidate


def pack_skill_zip(name: str) -> bytes:
    """Return the complete zip archive of skill ``name``.

    Members are rooted on the skill name (``patentworks/SKILL.md``,
    ``patentworks/flows/screening.md``, …) so a client unzips it straight into
    its skills directory — the same arcname shape the pre-BR implementation
    produced, so existing consumers see no layout change. Member order is
    sorted, making the archive byte-stable for an unchanged tree.
    """
    skill_dir = resolve_skill_dir(name)
    members = _shippable_members(skill_dir)
    if not members:
        # A 22-byte end-of-central-directory record IS a valid zip, so a client
        # unpacking it sees success-with-nothing — precisely the silent failure
        # this BR exists to kill. Fail typed instead (review F2). Reached when
        # the dir holds only dotfiles/bytecode, or when the tree changed between
        # the LIST and this DOWNLOAD.
        raise SkillShippingError(
            "SKILL_EMPTY", "skill exists but holds no shippable file")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in members:
            zf.write(p, arcname=f"{name}/{p.relative_to(skill_dir).as_posix()}")
    return buf.getvalue()
