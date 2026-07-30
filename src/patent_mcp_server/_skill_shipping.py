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
import os
import re
import zipfile
from pathlib import Path

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
        Route → 404. NEVER a 200 with an empty archive.
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
        return out
    for skill_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        members = _shippable_members(skill_dir)
        if not members:
            continue
        out.append({"name": skill_dir.name, "file_count": len(members)})
    return out


def resolve_skill_dir(name: str) -> Path:
    """Validate ``name`` and return the contained skill directory.

    Two independent traversal guards:
      1. ``name`` matches the safe-name rule (single segment, no slash / ``..``
         / absolute marker). ``../bin`` or ``a/b`` never passes.
      2. After ``.resolve()`` the candidate must still be a DIRECT child of the
         resolved skills root — catches whatever the regex might miss (symlink
         escape, unicode trickery, root itself).

    Raises :class:`SkillShippingError` (``SKILL_NAME_INVALID`` /
    ``SKILL_NOT_FOUND``); callers map both to 404.
    """
    if not isinstance(name, str) or not name or name in (".", ".."):
        raise SkillShippingError(
            "SKILL_NAME_INVALID",
            f"skill name must be a single path segment; got {name!r}",
        )
    if not _SAFE_NAME_RE.match(name):
        raise SkillShippingError(
            "SKILL_NAME_INVALID",
            f"skill name {name!r} contains characters outside [A-Za-z0-9._-] "
            "(no slash, no '..', no path separator — this is a traversal guard)",
        )
    root = skills_root().resolve()
    candidate = (root / name).resolve()
    if candidate.parent != root:
        raise SkillShippingError(
            "SKILL_NAME_INVALID",
            f"skill name {name!r} does not resolve to a direct child of the "
            "skills root (traversal rejected)",
        )
    if not candidate.is_dir():
        raise SkillShippingError(
            "SKILL_NOT_FOUND",
            f"no shippable skill named {name!r} (looked in {root})",
        )
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
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in _shippable_members(skill_dir):
            zf.write(p, arcname=f"{name}/{p.relative_to(skill_dir).as_posix()}")
    return buf.getvalue()
