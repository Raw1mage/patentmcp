"""Typed asset preflight + content assertions for delivery-oriented operations.

standard R17.2.4/5 (plan patentmcp_r17-minimum-operational-toolset, DD-4/DD-5):
before a delivery-oriented operation (cache_export) LANDS a working tree, it must
reject unresolved / empty / out-of-namespace assets, and — when the caller supplies
content assertions — enforce them. A transport-valid but EMPTY artifact must NOT be
reported delivery-ready (R17.2.5).

Pure module: takes an already-listed file inventory (the ``{rel, size, ...}`` dicts
from ``TokenStore.list_files``) + an optional assertions dict, returns a typed
verdict. No MCP / network / filesystem coupling → unit-testable in isolation and
reusable by any future delivery tool.

Verdict shape (fail-loud, no silent fallback — 天条 §11):
  {"ok": True}                                              # passes
  {"ok": False, "error_code": "EXPORT_EMPTY", "detail": …}  # empty tree
  {"ok": False, "error_code": "ASSERTION_FAILED", "detail": …, "failed": [...]}
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence


# Assertion kwargs the delivery gate understands (opt-in; absent => not checked).
ASSERTION_KEYS = ("assert_nonempty", "assert_min_files", "assert_contains_rel")


def _deliverable_files(files: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Files that count as deliverables: real files with a rel. (list_files already
    excludes the meta sidecar and dirs.)"""
    return [f for f in files if f.get("rel")]


def _nonempty_files(files: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [f for f in _deliverable_files(files) if (f.get("size") or 0) > 0]


def preflight_export(
    files: Sequence[Dict[str, Any]],
    *,
    assert_nonempty: Optional[bool] = None,
    assert_min_files: Optional[int] = None,
    assert_contains_rel: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Gate a delivery export before it lands.

    Base preflight (always): an export with zero deliverable files is refused
    (``EXPORT_EMPTY``) — a transport-valid but empty artifact is never
    delivery-ready (R17.2.5).

    Content assertions (opt-in — only checked when the corresponding kwarg is
    supplied, so an existing caller that passes none is byte-identical to the
    pre-R17 behaviour, 天条 §11):
      - ``assert_nonempty``: at least one deliverable file with size > 0
      - ``assert_min_files``: at least N deliverable files
      - ``assert_contains_rel``: every listed rel is present

    Returns a typed verdict dict; never raises for a business-rule failure.
    """
    deliverables = _deliverable_files(files)

    # Base gate: empty tree is not delivery-ready.
    if not deliverables:
        return {
            "ok": False,
            "error_code": "EXPORT_EMPTY",
            "detail": (
                "no deliverable files in the working tree; a transport-valid "
                "but empty artifact is not delivery-ready (R17.2.5). Produce or "
                "PUT deliverables into the cache before exporting."
            ),
        }

    failed: List[str] = []

    if assert_nonempty:
        if not _nonempty_files(files):
            failed.append(
                "assert_nonempty: every deliverable file is zero-length"
            )

    if assert_min_files is not None:
        if not isinstance(assert_min_files, int) or assert_min_files < 0:
            failed.append(
                f"assert_min_files: must be a non-negative int, got {assert_min_files!r}"
            )
        elif len(deliverables) < assert_min_files:
            failed.append(
                f"assert_min_files: expected >= {assert_min_files} deliverable "
                f"files, found {len(deliverables)}"
            )

    if assert_contains_rel:
        present = {f["rel"] for f in deliverables}
        missing = [rel for rel in assert_contains_rel if rel not in present]
        if missing:
            failed.append(
                f"assert_contains_rel: missing required rel(s): {missing}"
            )

    if failed:
        return {
            "ok": False,
            "error_code": "ASSERTION_FAILED",
            "detail": "one or more content assertions did not hold",
            "failed": failed,
        }

    return {"ok": True}


def extract_assertions(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Pull the recognised assertion kwargs out of a call's kwargs, dropping
    None values so an all-None call is treated as 'no assertions supplied'."""
    return {
        k: kwargs[k]
        for k in ASSERTION_KEYS
        if k in kwargs and kwargs[k] is not None
    }
