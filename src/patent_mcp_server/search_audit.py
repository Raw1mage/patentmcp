"""search_audit: machine-checkable rigor gate for the priorsearch flow.

Reads a search campaign's `matrix-log.jsonl` (one query per line) and scores
the *breadth* of the search against floor thresholds, so a thin "checked a few
hits and called it done" search cannot pass off as a complete landscape.

This module is PURE: it parses files and computes coverage. It issues no network
requests and runs no searches itself — it only audits the evidence the search
agent left behind (the matrix-log). Division of labour: the AI leaves search
evidence, this tool verifies the evidence.

matrix-log.jsonl line schema (see priorsearch.md §0 / design DD-1):
    {
      "query_id": "Q07",
      "source": "gpss",                 # gpss|epo|uspto|google
      "database": "USA",                # TWA/TWB/CNA/CNB/USA/USB | epo/google region
      "axis": {
        "class_codes": ["G06Q50/08"],   # IPC/CPC/USPC codes used (>=0)
        "class_scheme": "ipc",          # ipc|cpc|uspc
        "keywords": ["escrow"],         # keywords for this query
        "concept_group": "A",           # campaign concept group A-E
        "boolean": "AND",               # AND|OR|SINGLE
        "date_from": "2015-01-01",
        "date_to": "2026-06-28"
      },
      "hits": 42,                        # hit count (0 is valid evidence)
      "raw_ref": "raw/Q07.json"
    }
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Set, Tuple

# ── floor thresholds (design DD-2). campaign may raise, never lower. ──────
FLOORS: Dict[str, Any] = {
    "min_class_anchors": 3,    # distinct class codes across IPC/CPC/USPC
    "min_concept_groups": 3,   # distinct campaign concept groups touched
    "min_jurisdictions": 3,    # TW + CN + US all present
    "min_boolean_combos": 2,   # at least 2 boolean shapes (not all SINGLE)
    "uspc_required": True,     # US search must include >=1 USPC-anchored query
    "min_queries": 12,         # minimum cartesian coverage
}

# database code → jurisdiction bucket
_JURIS_PREFIX = {
    "TW": "TW", "CN": "CN", "US": "US",
}

# google/epo region codes that still count toward a jurisdiction
_REGION_JURIS = {
    "US": "US", "USA": "US", "USB": "US",
    "CN": "CN", "CNA": "CN", "CNB": "CN",
    "TW": "TW", "TWA": "TW", "TWB": "TW",
}


class MatrixLogError(Exception):
    """Raised when matrix-log.jsonl cannot be parsed at all (fail loud)."""


def _juris_of(database: str) -> Optional[str]:
    """Map a database/region code to a TW/CN/US jurisdiction bucket, or None."""
    if not database:
        return None
    db = database.strip().upper()
    if db in _REGION_JURIS:
        return _REGION_JURIS[db]
    pre = db[:2]
    return _JURIS_PREFIX.get(pre)


def parse_matrix_log(path: str) -> List[Dict[str, Any]]:
    """Parse matrix-log.jsonl into a list of query records. Skips blank lines.
    Raises MatrixLogError if the file is missing or every line is malformed."""
    if not os.path.isfile(path):
        raise MatrixLogError(f"matrix-log not found: {path}")
    records: List[Dict[str, Any]] = []
    bad = 0
    total = 0
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                rec = json.loads(line)
                if isinstance(rec, dict):
                    records.append(rec)
                else:
                    bad += 1
            except json.JSONDecodeError:
                bad += 1
    if total > 0 and bad == total:
        raise MatrixLogError(f"matrix-log unparseable: all {total} lines malformed in {path}")
    return records


def load_campaign_overrides(path: Optional[str]) -> Dict[str, Any]:
    """Read threshold overrides from 00_campaign.md front-matter-style markers.

    Campaign may RAISE floors via lines like:
        <!-- audit: min_queries=20 min_concept_groups=4 -->
    and may declare an explicit jurisdiction exclusion (escape hatch, DD-2 R1):
        <!-- audit: exclude_jurisdiction=TW reason="TW low value for this domain" -->
    Lowering a numeric floor below FLOORS is ignored (floor wins). Returns a
    dict of effective overrides actually applied (for transparency)."""
    overrides: Dict[str, Any] = {}
    if not path or not os.path.isfile(path):
        return overrides
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    for token in text.replace("\n", " ").split():
        if "=" not in token:
            continue
        key, _, val = token.partition("=")
        key = key.strip().lstrip("#").strip()
        val = val.strip().strip('"').strip()
        if key in ("min_class_anchors", "min_concept_groups", "min_jurisdictions",
                   "min_boolean_combos", "min_queries"):
            try:
                num = int(val)
            except ValueError:
                continue
            # raise-only: floor wins over any lower campaign value
            if num > FLOORS[key]:
                overrides[key] = num
        elif key == "exclude_jurisdiction":
            overrides.setdefault("exclude_jurisdiction", set())
            overrides["exclude_jurisdiction"].add(val.upper())
        elif key == "uspc_required" and val.lower() in ("true", "false"):
            # campaign may only TIGHTEN (true), never relax a true floor to false
            if val.lower() == "true":
                overrides["uspc_required"] = True
    return overrides


def effective_thresholds(overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Merge floors with raise-only overrides → the thresholds actually enforced."""
    eff = dict(FLOORS)
    for k, v in overrides.items():
        if k == "exclude_jurisdiction":
            continue
        eff[k] = v
    return eff


def compute_coverage(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Reduce matrix-log records to the five-axis coverage measurement."""
    class_codes: Set[str] = set()
    concept_groups: Set[str] = set()
    jurisdictions: Set[str] = set()
    boolean_shapes: Set[str] = set()
    uspc_in_axis = False
    per_jurisdiction: Dict[str, int] = {}
    per_database: Dict[str, int] = {}

    for r in records:
        axis = r.get("axis") or {}
        for c in (axis.get("class_codes") or []):
            if isinstance(c, str) and c.strip():
                class_codes.add(c.strip().upper().replace(" ", ""))
        cg = axis.get("concept_group")
        if isinstance(cg, str) and cg.strip():
            concept_groups.add(cg.strip().upper())
        scheme = (axis.get("class_scheme") or "").strip().lower()
        if scheme == "uspc" and (axis.get("class_codes")):
            uspc_in_axis = True
        b = (axis.get("boolean") or "").strip().upper()
        if b:
            boolean_shapes.add(b)
        db = r.get("database") or ""
        if db:
            per_database[db] = per_database.get(db, 0) + 1
        j = _juris_of(db)
        if j:
            jurisdictions.add(j)
            per_jurisdiction[j] = per_jurisdiction.get(j, 0) + 1

    return {
        "class_anchors": len(class_codes),
        "concept_groups": len(concept_groups),
        "jurisdictions": len(jurisdictions),
        "boolean_combos": len([b for b in boolean_shapes if b != "SINGLE"]) or
                          (1 if boolean_shapes else 0),
        "uspc_in_axis": uspc_in_axis,
        "queries": len(records),
        "_jurisdiction_set": sorted(jurisdictions),
        "per_jurisdiction": per_jurisdiction,
        "per_database": per_database,
        "_class_code_set": sorted(class_codes),
        "_concept_group_set": sorted(concept_groups),
        "_boolean_shapes": sorted(boolean_shapes),
    }


def _boolean_combo_count(records: List[Dict[str, Any]]) -> int:
    """Distinct non-trivial boolean shapes. A search that is entirely SINGLE
    (single-word dragnet) scores 0 boolean combos — the anti-laziness signal."""
    shapes: Set[str] = set()
    for r in records:
        b = ((r.get("axis") or {}).get("boolean") or "").strip().upper()
        if b and b != "SINGLE":
            shapes.add(b)
    return len(shapes)


def audit(matrix_log_path: str, campaign_path: Optional[str] = None) -> Dict[str, Any]:
    """Audit a matrix-log against effective thresholds. Returns the verdict
    envelope (design DD-3). PASS = all axes meet floor; FAIL = any axis below
    floor; WARN = all floors met but a jurisdiction is severely under-covered."""
    records = parse_matrix_log(matrix_log_path)
    overrides = load_campaign_overrides(campaign_path)
    thresholds = effective_thresholds(overrides)
    excluded: Set[str] = overrides.get("exclude_jurisdiction", set())

    cov = compute_coverage(records)
    cov["boolean_combos"] = _boolean_combo_count(records)

    # jurisdiction floor honours explicit campaign exclusions (escape hatch)
    required_juris = {"TW", "CN", "US"} - excluded
    present_juris = set(cov["_jurisdiction_set"])
    missing_juris = sorted(required_juris - present_juris)
    juris_met = len(present_juris & required_juris) >= min(
        thresholds["min_jurisdictions"], len(required_juris))

    gaps: List[str] = []

    if cov["class_anchors"] < thresholds["min_class_anchors"]:
        gaps.append(
            f"分類錨點不足：{cov['class_anchors']} < {thresholds['min_class_anchors']}"
            f"（需跨 IPC/CPC/USPC 至少 {thresholds['min_class_anchors']} 個不同分類碼）")
    if cov["concept_groups"] < thresholds["min_concept_groups"]:
        gaps.append(
            f"關鍵字概念群不足：{cov['concept_groups']} < {thresholds['min_concept_groups']}"
            f"（campaign A-E 概念群至少觸及 {thresholds['min_concept_groups']} 群）")
    if not juris_met:
        gaps.append(
            f"三地覆蓋不足：缺 {missing_juris}（如刻意排除，需在 00_campaign.md 標"
            f" exclude_jurisdiction=<地> reason=...）")
    if cov["boolean_combos"] < thresholds["min_boolean_combos"]:
        gaps.append(
            f"AND/OR 組合不足：{cov['boolean_combos']} < {thresholds['min_boolean_combos']}"
            f"（不可全 SINGLE 單詞海撈，需多種布林型態交叉）")
    if thresholds.get("uspc_required") and ("US" in required_juris) and not cov["uspc_in_axis"]:
        gaps.append(
            "USPC 未入軸：US 檢索至少 1 條須以 USPC 為 class_scheme 限縮範圍")
    if cov["queries"] < thresholds["min_queries"]:
        gaps.append(
            f"總查詢筆數不足：{cov['queries']} < {thresholds['min_queries']}"
            f"（五維交叉的最低笛卡兒覆蓋）")

    # WARN: floors met but a required jurisdiction has < 2 queries (skewed)
    warn_notes: List[str] = []
    if not gaps:
        for j in required_juris:
            n = cov["per_jurisdiction"].get(j, 0)
            if n < 2:
                warn_notes.append(f"{j} 僅 {n} 條查詢，分佈偏斜（建議補強至 ≥2）")

    if gaps:
        verdict = "FAIL"
    elif warn_notes:
        verdict = "WARN"
    else:
        verdict = "PASS"

    return {
        "verdict": verdict,
        "coverage": {
            "class_anchors": cov["class_anchors"],
            "concept_groups": cov["concept_groups"],
            "jurisdictions": cov["jurisdictions"],
            "boolean_combos": cov["boolean_combos"],
            "uspc_in_axis": cov["uspc_in_axis"],
            "queries": cov["queries"],
        },
        "thresholds": {k: v for k, v in thresholds.items()},
        "gaps": gaps,
        "warnings": warn_notes,
        "per_jurisdiction": cov["per_jurisdiction"],
        "per_database": cov["per_database"],
        "applied_overrides": {
            k: (sorted(v) if isinstance(v, set) else v)
            for k, v in overrides.items()
        },
        "evidence": {
            "class_codes": cov["_class_code_set"],
            "concept_groups": cov["_concept_group_set"],
            "boolean_shapes": cov["_boolean_shapes"],
            "jurisdictions": cov["_jurisdiction_set"],
        },
    }
