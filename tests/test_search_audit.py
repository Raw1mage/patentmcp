"""Unit tests for search_audit: the priorsearch rigor gate (DD-1..DD-3).

Covers:
  - PASS:  a broad search meeting all five floors (class axis CPC/IPC only)
  - NO-USPC: a US search with no USPC still PASSes (USPC dropped per user rule 2026-06-28)
  - FAIL: thin search (too few queries / anchors / concept groups / single-word dragnet)
  - campaign override: raise-only floors + explicit jurisdiction exclusion escape hatch
  - malformed log fails loud

Run: .venv/bin/python -m pytest tests/test_search_audit.py
 or: .venv/bin/python tests/test_search_audit.py
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from patent_mcp_server import search_audit as sa


def _q(qid, source, db, codes, scheme, kws, cg, boolean):
    return {
        "query_id": qid, "source": source, "database": db,
        "axis": {
            "class_codes": codes, "class_scheme": scheme,
            "keywords": kws, "concept_group": cg, "boolean": boolean,
            "date_from": "2015-01-01", "date_to": "2026-06-28",
        },
        "hits": 10, "raw_ref": f"raw/{qid}.json",
    }


def _write_jsonl(records):
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


def _broad_log():
    """A search that meets every floor: 3 jurisdictions, >=3 anchors,
    >=3 concept groups, >=2 boolean shapes, >=12 queries.
    Class axis is CPC/IPC only (USPC no longer used per user rule 2026-06-28)."""
    recs = []
    # TW (Chinese kw, ipc)
    recs.append(_q("Q01", "gpss", "TWA", ["G06Q50/08"], "ipc", ["履約"], "A", "AND"))
    recs.append(_q("Q02", "gpss", "TWA", ["G06Q10/06"], "ipc", ["風險"], "B", "OR"))
    recs.append(_q("Q03", "gpss", "TWB", ["G06F21/64"], "ipc", ["雜湊"], "D", "AND"))
    # CN
    recs.append(_q("Q04", "gpss", "CNA", ["G06Q50/08"], "ipc", ["验收"], "A", "AND"))
    recs.append(_q("Q05", "gpss", "CNA", ["G06Q20/02"], "ipc", ["托管"], "C", "OR"))
    recs.append(_q("Q06", "gpss", "CNB", ["G06F21/64"], "ipc", ["存证"], "D", "AND"))
    # US (English kw) — CPC/IPC only, no USPC
    recs.append(_q("Q07", "gpss", "USA", ["G06Q50/08"], "cpc", ["escrow"], "A", "AND"))
    recs.append(_q("Q08", "gpss", "USA", ["G06Q40/04"], "cpc", ["milestone"], "C", "AND"))
    recs.append(_q("Q09", "gpss", "USA", ["G06Q10/06"], "cpc", ["risk score"], "E", "OR"))
    recs.append(_q("Q10", "gpss", "USB", ["G06F21/64"], "cpc", ["hash"], "D", "AND"))
    recs.append(_q("Q11", "gpss", "USA", ["G06N5/02"], "cpc", ["knowledge base"], "B", "OR"))
    recs.append(_q("Q12", "gpss", "USA", ["G06Q20/02"], "cpc", ["payment release"], "C", "AND"))
    return recs


class TestSearchAuditPass(unittest.TestCase):
    def test_broad_search_passes(self):
        path = _write_jsonl(_broad_log())
        try:
            res = sa.audit(path)
            self.assertEqual(res["verdict"], "PASS", res["gaps"])
            self.assertEqual(res["gaps"], [])
            self.assertGreaterEqual(res["coverage"]["queries"], 12)
            self.assertEqual(res["coverage"]["jurisdictions"], 3)
        finally:
            os.unlink(path)


class TestSearchAuditNoUspc(unittest.TestCase):
    def test_cpc_ipc_only_still_passes(self):
        """USPC dropped per user rule 2026-06-28: a CPC/IPC-only US search
        (no USPC axis anywhere) must still PASS — USPC is no longer required."""
        recs = _broad_log()  # already CPC/IPC only
        path = _write_jsonl(recs)
        try:
            res = sa.audit(path)
            self.assertEqual(res["verdict"], "PASS", res["gaps"])
            self.assertFalse(any("USPC" in g for g in res["gaps"]), res["gaps"])
        finally:
            os.unlink(path)


class TestSearchAuditFailThin(unittest.TestCase):
    def test_thin_single_word_dragnet_fails(self):
        """A few single-word queries on one anchor — the 'checked a few, done' case."""
        recs = [
            _q("Q01", "gpss", "USA", ["G06Q50/08"], "cpc", ["escrow"], "A", "SINGLE"),
            _q("Q02", "gpss", "USA", ["G06Q50/08"], "cpc", ["milestone"], "A", "SINGLE"),
            _q("Q03", "gpss", "USB", ["G06Q50/08"], "cpc", ["payment"], "A", "SINGLE"),
        ]
        path = _write_jsonl(recs)
        try:
            res = sa.audit(path)
            self.assertEqual(res["verdict"], "FAIL")
            joined = " ".join(res["gaps"])
            self.assertIn("分類錨點", joined)        # only 1 anchor
            self.assertIn("概念群", joined)          # only 1 group
            self.assertIn("三地", joined)            # only US
            self.assertIn("AND/OR", joined)          # all SINGLE
            self.assertIn("總查詢筆數", joined)       # 3 < 12
        finally:
            os.unlink(path)


class TestCampaignOverride(unittest.TestCase):
    def test_raise_only_and_exclusion(self):
        """campaign can raise min_queries and exclude a jurisdiction with reason."""
        recs = _broad_log()
        # drop all TW queries; campaign explicitly excludes TW
        recs = [r for r in recs if not r["database"].startswith("TW")]
        log_path = _write_jsonl(recs)
        fd, camp_path = tempfile.mkstemp(suffix=".md")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("# Campaign\n")
            fh.write('<!-- audit: exclude_jurisdiction=TW reason="TW low value for this domain" -->\n')
        try:
            res = sa.audit(log_path, camp_path)
            # TW excluded → jurisdiction floor satisfied by CN+US
            self.assertNotIn(
                "三地", " ".join(res["gaps"]),
                f"TW exclusion should waive the jurisdiction gap; got {res['gaps']}")
            self.assertEqual(res["applied_overrides"].get("exclude_jurisdiction"), ["TW"])
        finally:
            os.unlink(log_path)
            os.unlink(camp_path)

    def test_lower_override_ignored(self):
        """campaign trying to LOWER a floor is ignored (floor wins)."""
        fd, camp_path = tempfile.mkstemp(suffix=".md")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write('<!-- audit: min_queries=3 -->\n')  # below floor 12
        try:
            ov = sa.load_campaign_overrides(camp_path)
            self.assertNotIn("min_queries", ov)  # lower value rejected
            eff = sa.effective_thresholds(ov)
            self.assertEqual(eff["min_queries"], 12)
        finally:
            os.unlink(camp_path)


class TestMalformed(unittest.TestCase):
    def test_all_malformed_raises(self):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("not json\n{also bad\n")
        try:
            with self.assertRaises(sa.MatrixLogError):
                sa.parse_matrix_log(path)
        finally:
            os.unlink(path)

    def test_missing_file_raises(self):
        with self.assertRaises(sa.MatrixLogError):
            sa.parse_matrix_log("/nonexistent/matrix-log.jsonl")


if __name__ == "__main__":
    unittest.main()
