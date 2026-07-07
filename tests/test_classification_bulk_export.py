"""Tests for patent_bulk_export — classification-axis bulk export.

Covers plans/patentmcp_classification-bulk-export (BR_20260707):
monkeypatched GPSS client, no real network. Pattern follows
test_search_dispatcher.py (direct async calls via asyncio.run).

Run: uv run pytest tests/test_classification_bulk_export.py -q
"""
import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import patent_mcp_server.patents as P
import patent_mcp_server.search_dispatcher as SD


def _gpss_page_payload(pubs, total):
    """One GPSS page: pubs is the slice returned for this expSkip window."""
    return {
        "success": True, "status": "success", "message": None,
        "total": total, "qty": len(pubs),
        "data": {"gpss-API": {"patent": {"patentcontent": [
            {
                "publication-reference": {"doc-number": p},
                "patent-title": {"english-title": f"Title {p}"},
                "claims": {"claim": [{"claim-text": "1. A device."}]},
            } for p in pubs
        ]}}},
    }


class PagingGPSS:
    """GPSS fake that honours expQty(num)/expSkip(skip) over a fixed corpus,
    and records the fields it was asked for (to assert expFld forcing)."""

    def __init__(self, corpus=None, configured=True, fail=False):
        self.corpus = list(corpus or [])
        self._configured = configured
        self.fail = fail
        self.calls = 0
        self.seen_fields = []
        self.seen_num = []

    def configured(self):
        return self._configured

    async def search(self, *, conditions=None, databases=None, fields=None,
                     num=30, skip=0, fmt="json"):
        self.calls += 1
        self.seen_fields.append(fields)
        self.seen_num.append(num)
        if self.fail:
            return {"success": False, "error": "GPSS 500 boom"}
        if not self.corpus:
            return {"success": False, "status": "success",
                    "message": "no record found", "total": 0}
        window = self.corpus[skip:skip + num]
        return _gpss_page_payload(window, total=len(self.corpus))


def _bulk(spec_kwargs, gpss):
    spec = SD.normalize_query(**spec_kwargs)
    return asyncio.run(SD.bulk_export(spec, gpss_client=gpss))


# ── T4.1: pagination — multi-page accumulate / stop at total / stop at num ──
class Pagination(unittest.TestCase):
    def test_accumulates_across_pages(self):
        corpus = [f"CN{i:04d}" for i in range(450)]  # > one 200-page
        gpss = PagingGPSS(corpus=corpus)
        out = _bulk({"ipc": "G16H40/67", "databases": ["CN"], "num": 450}, gpss)
        self.assertTrue(out["success"])
        self.assertEqual(out["source"], "gpss")
        self.assertEqual(len(out["records"]), 450)
        self.assertGreaterEqual(gpss.calls, 3)  # 200 + 200 + 50
        # provenance has one hit entry per page
        hits = [p for p in out["provenance"] if p["status"] == "hit"]
        self.assertGreaterEqual(len(hits), 3)

    def test_stops_at_total_when_axis_smaller_than_num(self):
        corpus = [f"CN{i:04d}" for i in range(120)]
        gpss = PagingGPSS(corpus=corpus)
        out = _bulk({"ipc": "G16H40/67", "num": 2000}, gpss)
        self.assertTrue(out["success"])
        self.assertEqual(len(out["records"]), 120)  # exhausted, not 2000

    def test_stops_at_num_when_axis_larger(self):
        corpus = [f"CN{i:04d}" for i in range(1000)]
        gpss = PagingGPSS(corpus=corpus)
        out = _bulk({"ipc": "G16H40/67", "num": 300}, gpss)
        self.assertTrue(out["success"])
        self.assertEqual(len(out["records"]), 300)

    def test_num_hard_capped(self):
        corpus = [f"CN{i:05d}" for i in range(6000)]
        gpss = PagingGPSS(corpus=corpus)
        out = _bulk({"ipc": "G16H40/67", "num": 999999}, gpss)
        self.assertTrue(out["success"])
        self.assertLessEqual(len(out["records"]), SD.BULK_EXPORT_MAX)


# ── T4.2: expFld forced full — caller cannot narrow the fields ──
class ForcedFields(unittest.TestCase):
    def test_full_expfld_forced(self):
        gpss = PagingGPSS(corpus=["CN1", "CN2"])
        out = _bulk({"ipc": "G16H40/67"}, gpss)
        self.assertTrue(out["success"])
        # every page requested the full field set (DD-3)
        for f in gpss.seen_fields:
            self.assertEqual(f, SD._BULK_FIELDS)
            self.assertIn("TI", f)
            self.assertIn("PA", f)
            self.assertIn("CL", f)


# ── T4.3: official miss → true zero, NO scraper fallback ──
class MissNoScraper(unittest.TestCase):
    def test_zero_hits_true_zero(self):
        gpss = PagingGPSS(corpus=[])  # GPSS returns "no record found"
        out = _bulk({"ipc": "NOSUCH/00"}, gpss)
        # success=True with empty records is a TRUE zero (not an error)
        self.assertTrue(out["success"])
        self.assertEqual(out["records"], [])
        self.assertEqual(out["source"], "gpss")
        # no SCRAPING_REQUIRED, no error_code
        self.assertNotIn("error_code", out)
        prov = out["provenance"]
        self.assertTrue(any(p["reason"] == "zero_hits" for p in prov))
        # provenance never mentions gpatents / scraping
        self.assertFalse(any(p["source"] == "gpatents" for p in prov))
        self.assertFalse(any(p.get("scraping") for p in prov))

    def test_tool_level_no_scraping_key(self):
        # full tool path: patent_bulk_export has no allow_scraping arg at all
        orig = P.gpss_client
        P.gpss_client = PagingGPSS(corpus=[])  # type: ignore
        try:
            out = asyncio.run(P.patent_bulk_export(ipc="NOSUCH/00"))
        finally:
            P.gpss_client = orig  # type: ignore
        self.assertTrue(out["success"])
        self.assertEqual(out["records"], [])
        self.assertNotIn("error_code", out)


# ── T4.4: pure classification axis + large num; no keyword narrowing ──
class PureAxis(unittest.TestCase):
    def test_requires_classification_axis(self):
        gpss = PagingGPSS(corpus=["CN1"])
        out = _bulk({"databases": ["CN"], "num": 100}, gpss)  # no ipc/cpc/uspc
        self.assertFalse(out["success"])
        self.assertEqual(out["error_code"], "INVALID_PARAMS")
        self.assertEqual(gpss.calls, 0)

    def test_num_passed_to_expqty(self):
        corpus = [f"CN{i:04d}" for i in range(50)]
        gpss = PagingGPSS(corpus=corpus)
        _bulk({"ipc": "G16H40/67", "num": 50}, gpss)
        # first page expQty == min(page_size, num)
        self.assertEqual(gpss.seen_num[0], min(SD._BULK_PAGE, 50))


# ── GPSS not configured → fail fast, no fallback ──
class NotConfigured(unittest.TestCase):
    def test_gpss_not_configured(self):
        gpss = PagingGPSS(corpus=["CN1"], configured=False)
        out = _bulk({"ipc": "G16H40/67"}, gpss)
        self.assertFalse(out["success"])
        self.assertEqual(out["error_code"], "GPSS_NOT_CONFIGURED")
        self.assertEqual(gpss.calls, 0)


# ── tool wiring: patent_bulk_export lands records into patentdb ──
class ToolWiring(unittest.TestCase):
    def test_tool_absorbs_into_patentdb(self):
        orig_gpss = P.gpss_client
        orig_pdb_import = P._pdb.import_records
        captured = {}

        def fake_import(records, acquisition_cost="low", conn=None):
            captured["n"] = len(records)
            captured["cost"] = acquisition_cost
            return {"imported": len(records), "updated": 0, "skipped": 0}

        P.gpss_client = PagingGPSS(corpus=["CN1", "CN2", "CN3"])  # type: ignore
        P._pdb.import_records = fake_import  # type: ignore
        try:
            out = asyncio.run(P.patent_bulk_export(ipc="G16H40/67", num=3))
        finally:
            P.gpss_client = orig_gpss  # type: ignore
            P._pdb.import_records = orig_pdb_import  # type: ignore
        self.assertTrue(out["success"])
        self.assertEqual(captured["n"], 3)
        self.assertEqual(out["patentdb_absorb"]["imported"], 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
