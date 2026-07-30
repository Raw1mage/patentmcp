"""Suite-wide fixture root — pins PATENTS_SKILLS_ROOT before ANY test imports.

Why this file exists (VANS re-verification of BR_20260730)
==========================================================

``patents.py`` freezes the doctrine path at MODULE IMPORT time::

    _DOCTRINE_PATH = _skills_root() / "patentworks" / "SKILL.md"   # :79

``_skills_root()`` honours ``PATENTS_SKILLS_ROOT`` and otherwise derives from
``parents[4]``, which in the repo layout resolves OUTSIDE the repo. So whichever
test module imports ``patents`` first decides the path for the entire session.

Five test modules each carried their own ``os.environ.setdefault(...)`` line;
four others imported the same modules without one. Collection order therefore
decided the outcome::

    PATENTS_SKILLS_ROOT=skills pytest tests   -> 393 passed
    pytest tests                              ->   7 failed, 386 passed

Both runs exercised identical code. The green one was green because the caller
happened to export the variable — the same defect shape as the BR this suite was
written for: a check that does not cover the case returns green, and that green
is indistinguishable from correctness.

Setting it here (before collection imports anything) makes a bare ``pytest``
reproduce what CI and the container see, and replaces the five drifting
per-module copies with one. The path is absolute and derived from THIS file, so
it no longer depends on the caller's working directory either.
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault(
    "PATENTS_SKILLS_ROOT", str(Path(__file__).resolve().parent.parent / "skills")
)
