"""Thin re-export shim. The screening-table logic moved to `._pure.screening`
so both the container and landing scripts import the same deterministic code.
Every existing `from .screening_table import X` keeps working unchanged.
"""
from __future__ import annotations

from ._pure.screening import *  # noqa: F401,F403
from ._pure.screening import (  # noqa: F401
    AI_KEYS,
    COLUMNS,
    CORE_KEYS,
    KNOWN_GAPS,
    PRESETS,
    _as_list,
    _claim1_is_empty,
    _g,
    _render,
    build_csv,
    dedup_by_family,
    epo_biblio_to_record,
    google_to_records,
    gpss_to_records,
    ppubs_to_records,
    resolve_columns,
)
