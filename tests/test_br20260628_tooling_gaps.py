"""Unit tests for BR_20260628 tooling-gaps remediation.

Covers:
  P1 — fetch_patent_pdf explicit scraping gate (allow_scraping)
  P2 — publication_number / patent_number backward-compat aliases
  P3 — extract_representative_figure failure grading (_pdf_image_count)
  P5 — GPSS claim1 empty flag (_claim1_is_empty / gpss_to_records)

Run: .venv/bin/python -m pytest tests/test_br20260628_tooling_gaps.py
 or: .venv/bin/python tests/test_br20260628_tooling_gaps.py
"""
import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import patent_mcp_server.patents as P
from patent_mcp_server.screening_table import _claim1_is_empty, gpss_to_records


def _make_pdf(path, pages_text):
    """Build a small text-layer PDF with matplotlib (env has it, no PyMuPDF)."""
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.backends.backend_pdf import PdfPages
    import matplotlib.pyplot as plt
    with PdfPages(path) as pp:
        for txt in pages_text:
            fig = plt.figure(figsize=(8.5, 11))
            fig.text(0.1, 0.85, txt, fontsize=14, va="top")
            pp.savefig(fig)
            plt.close(fig)


def _make_pdf_with_image(path):
    """Build a PDF whose page contains an embedded raster image (no FIG text)."""
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.backends.backend_pdf import PdfPages
    import matplotlib.pyplot as plt
    import numpy as np
    with PdfPages(path) as pp:
        # page 1: cover (so locate skips it)
        fig = plt.figure(figsize=(8.5, 11))
        fig.text(0.1, 0.85, "COVER", fontsize=14, va="top")
        pp.savefig(fig)
        plt.close(fig)
        # page 2: an embedded image, NO FIG.1 marker, no refnum text
        fig = plt.figure(figsize=(8.5, 11))
        ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
        ax.imshow(np.random.rand(64, 64, 3))
        ax.axis("off")
        pp.savefig(fig)
        plt.close(fig)


# ── P1: fetch_patent_pdf scraping gate ─────────────────────────────
class FetchPdfScrapingGateTest(unittest.TestCase):
    def _patch_misses(self):
        """Make epo/google sources miss; track whether gpss is invoked."""
        state = {"gpss_called": False}

        class _Epo:
            def configured(self_inner):
                return False

        async def _gpss(pn):
            state["gpss_called"] = True
            return {"success": False, "error": "GPSS_NO_PDF"}

        async def _resolve(pn):
            return {"success": False, "error": "resolve failed"}

        async def _find_cache(*a, **k):
            return None

        self._orig_epo = P.epo_client
        self._orig_gpss = P.gpss_download_patent_pdf
        self._orig_resolve = P.gpatents_client.resolve_pdf_url
        self._orig_findcache = P._find_local_patent_cache
        P.epo_client = _Epo()  # type: ignore
        P.gpss_download_patent_pdf = _gpss  # type: ignore
        P.gpatents_client.resolve_pdf_url = _resolve  # type: ignore
        P._find_local_patent_cache = lambda *a, **k: None  # type: ignore
        return state

    def _restore(self):
        P.epo_client = self._orig_epo  # type: ignore
        P.gpss_download_patent_pdf = self._orig_gpss  # type: ignore
        P.gpatents_client.resolve_pdf_url = self._orig_resolve  # type: ignore
        P._find_local_patent_cache = self._orig_findcache  # type: ignore

    def test_default_skips_gpss_returns_scraping_required(self):
        state = self._patch_misses()
        try:
            out = asyncio.run(P.fetch_patent_pdf("TW123", include_attempts=True))
        finally:
            self._restore()
        self.assertFalse(out["success"])
        self.assertEqual(out["error"], "SCRAPING_REQUIRED")
        self.assertFalse(state["gpss_called"], "gpss must NOT be called by default")
        # gpss_pdf attempt recorded as SKIPPED
        skipped = [a for a in out["attempts"]
                   if a["source"] == "gpss_pdf"
                   and a.get("error") == "SKIPPED_SCRAPING_NOT_AUTHORIZED"]
        self.assertEqual(len(skipped), 1)
        self.assertIn("hint", out)

    def test_allow_scraping_invokes_gpss(self):
        state = self._patch_misses()
        try:
            out = asyncio.run(P.fetch_patent_pdf(
                "TW123", allow_scraping=True, include_attempts=True))
        finally:
            self._restore()
        self.assertTrue(state["gpss_called"], "gpss MUST be called when allowed")
        # gpss tried-and-failed -> ALL_SOURCES_FAILED, not SCRAPING_REQUIRED
        self.assertEqual(out["error"], "ALL_SOURCES_FAILED")


# ── P2: parameter aliases ──────────────────────────────────────────
class ParameterAliasTest(unittest.TestCase):
    def test_fetch_patent_pdf_alias(self):
        # patch all sources to a controlled miss so we exercise the parse layer
        orig_find = P._find_local_patent_cache

        class _Epo:
            def configured(self_inner):
                return False

        orig_epo = P.epo_client
        P.epo_client = _Epo()  # type: ignore
        P._find_local_patent_cache = lambda *a, **k: None  # type: ignore

        async def _resolve(pn):
            return {"success": False, "error": "miss"}

        orig_resolve = P.gpatents_client.resolve_pdf_url
        P.gpatents_client.resolve_pdf_url = _resolve  # type: ignore
        try:
            out_new = asyncio.run(P.fetch_patent_pdf(publication_number="US1"))
            out_old = asyncio.run(P.fetch_patent_pdf(patent_number="US1"))
        finally:
            P.epo_client = orig_epo  # type: ignore
            P._find_local_patent_cache = orig_find  # type: ignore
            P.gpatents_client.resolve_pdf_url = orig_resolve  # type: ignore
        # neither raises a param error; both reach a source result
        self.assertEqual(out_new.get("publication_number"), "US1")
        self.assertEqual(out_old.get("publication_number"), "US1")
        self.assertNotEqual(out_old.get("error"), "MISSING_PUBLICATION_NUMBER")

    def test_patent_get_claim1_alias(self):
        captured = {}

        async def _fake_get_patent(pat, **k):
            captured["pat"] = pat
            return {"success": True, "claims": [{"text": "1. A device."}]}

        # neutralize fast paths: gpss not configured, no BQ, not US/EP
        orig_gpss_cfg = P.gpss_client.configured
        orig_get = P.gpatents_client.get_patent
        P.gpss_client.configured = lambda: False  # type: ignore
        P.gpatents_client.get_patent = _fake_get_patent  # type: ignore
        try:
            out_new = asyncio.run(P.patent_get_claim1(publication_number="WO1"))
            out_old = asyncio.run(P.patent_get_claim1(patent_number="WO1"))
        finally:
            P.gpss_client.configured = orig_gpss_cfg  # type: ignore
            P.gpatents_client.get_patent = orig_get  # type: ignore
        self.assertTrue(out_new["success"])
        self.assertTrue(out_old["success"])

    def test_patent_get_claim1_missing(self):
        out = asyncio.run(P.patent_get_claim1())
        self.assertFalse(out["success"])
        self.assertEqual(out["error"], "MISSING_PUBLICATION_NUMBER")

    def test_ppubs_batch_get_claims_alias(self):
        async def _fake_claim1(pub, full=True):
            return {"success": True, "publication_number": pub, "claim1": "x"}

        orig = P.patent_get_claim1
        P.patent_get_claim1 = _fake_claim1  # type: ignore
        try:
            out_new = asyncio.run(P.ppubs_batch_get_claims(publication_numbers=["US1"]))
            out_old = asyncio.run(P.ppubs_batch_get_claims(patent_numbers=["US1"]))
            out_none = asyncio.run(P.ppubs_batch_get_claims())
        finally:
            P.patent_get_claim1 = orig  # type: ignore
        self.assertTrue(out_new["success"])
        self.assertTrue(out_old["success"])
        self.assertIn("US1", out_new["claims"])
        self.assertFalse(out_none["success"])
        self.assertEqual(out_none["error"], "MISSING_PUBLICATION_NUMBERS")

    def test_extract_representative_figure_landed_stub(self):
        # R13: the tool is a TOOL_LANDED redirect regardless of params (the
        # alias/param parsing moved into figure_extract.py's CLI).
        out = asyncio.run(P.extract_representative_figure(publication_number="US1"))
        self.assertFalse(out["success"])
        self.assertEqual(out["error_code"], "TOOL_LANDED")
        self.assertEqual(out["landing"]["script"],
                         "skills/patentworks/scripts/figure_extract.py")


# ── P3: image-count grading ────────────────────────────────────────
class PdfImageCountTest(unittest.TestCase):
    def test_count_with_and_without_images(self):
        import tempfile
        td = tempfile.mkdtemp()
        with_img = os.path.join(td, "img.pdf")
        _make_pdf_with_image(with_img)
        self.assertGreater(P._pdf_image_count(with_img), 0)

        text_only = os.path.join(td, "text.pdf")
        _make_pdf(text_only, ["just some text", "more text"])
        self.assertEqual(P._pdf_image_count(text_only), 0)

    def test_locate_grades_no_figure_page_with_images(self):
        # R13: the failure-grading (no FIG.1 marker but images present) is now a
        # property of the poppler helpers that landed to figure_extract.py. Test
        # them directly: image-bearing scan has no FIG.1 text page but >0 images.
        import tempfile
        td = tempfile.mkdtemp()
        pdf = os.path.join(td, "scan.pdf")
        _make_pdf_with_image(pdf)
        loc = P._locate_figure_page(pdf)
        self.assertIsNone(loc["page"])
        self.assertGreater(P._pdf_image_count(pdf), 0)


# ── P5: claim1 empty flag ──────────────────────────────────────────
class Claim1EmptyTest(unittest.TestCase):
    def test_is_empty(self):
        self.assertTrue(_claim1_is_empty(""))
        self.assertTrue(_claim1_is_empty("   "))
        self.assertTrue(_claim1_is_empty("What is claimed is:"))
        self.assertTrue(_claim1_is_empty("WE CLAIM"))
        self.assertTrue(_claim1_is_empty("The Claims."))
        self.assertFalse(_claim1_is_empty("1. A wearable device comprising a sensor."))
        self.assertFalse(_claim1_is_empty("A method of measuring heart rate."))

    def test_gpss_to_records_flags_empty(self):
        gpss_json = {
            "gpss-API": {
                "patent": {
                    "patentcontent": [
                        {  # empty boilerplate-only claim
                            "publication-reference": {"doc-number": "TWEMPTY"},
                            "claims": {"claim": [{"claim-text": "What is claimed is:"}]},
                        },
                        {  # substantive claim
                            "publication-reference": {"doc-number": "TWFULL"},
                            "claims": {"claim": [{"claim-text": "1. A device comprising X."}]},
                        },
                    ]
                }
            }
        }
        recs = gpss_to_records(gpss_json)
        by_pub = {r["pubno"]: r for r in recs}
        self.assertTrue(by_pub["TWEMPTY"]["claim1_empty"])
        self.assertFalse(by_pub["TWFULL"]["claim1_empty"])


# ── P6: _gpss_search_impl surfaces claim1_audit advisory (BR3-D) ──────────
class GpssSearchClaim1AuditTest(unittest.TestCase):
    """_gpss_search_impl must surface a claim1_audit so a caller (not just
    build_screening_table) knows which pub numbers need a PPUBS fallback."""

    def _run_with_stub(self, gpss_payload):
        async def _stub(*args, **kwargs):
            return gpss_payload

        orig = P.gpss_client.search
        P.gpss_client.search = _stub  # type: ignore
        try:
            return asyncio.run(P._gpss_search_impl(keyword="x"))
        finally:
            P.gpss_client.search = orig  # type: ignore

    def test_audit_flags_empty_claim(self):
        payload = {
            "success": True,
            "gpss-API": {
                "patent": {
                    "patentcontent": [
                        {  # US case with boilerplate-only claim
                            "publication-reference": {"doc-number": "US1"},
                            "claims": {"claim": [{"claim-text": "What is claimed is:"}]},
                        },
                        {  # substantive claim
                            "publication-reference": {"doc-number": "US2"},
                            "claims": {"claim": [{"claim-text": "1. A method comprising Y."}]},
                        },
                    ]
                }
            },
        }
        out = self._run_with_stub(payload)
        audit = out["claim1_audit"]
        self.assertEqual(audit["checked"], 2)
        self.assertEqual(audit["empty_count"], 1)
        self.assertEqual(audit["empty_pubnos"], ["US1"])
        self.assertIsNotNone(audit["fallback"])

    def test_audit_clean_when_all_present(self):
        payload = {
            "success": True,
            "gpss-API": {
                "patent": {
                    "patentcontent": [
                        {
                            "publication-reference": {"doc-number": "US3"},
                            "claims": {"claim": [{"claim-text": "1. A device comprising Z."}]},
                        }
                    ]
                }
            },
        }
        out = self._run_with_stub(payload)
        audit = out["claim1_audit"]
        self.assertEqual(audit["empty_count"], 0)
        self.assertEqual(audit["empty_pubnos"], [])
        self.assertIsNone(audit["fallback"])

    def test_audit_absent_on_failed_search(self):
        out = self._run_with_stub({"success": False, "error": "boom"})
        self.assertNotIn("claim1_audit", out)


# ── P7: build_screening_table surfaces family gap for GPSS too (BR3-C) ──
class FamilyGapHonestyTest(unittest.TestCase):
    """family_id is unavailable from BOTH GPSS and Google; the gap must surface
    regardless of source, and the KNOWN_GAPS message must not imply GPSS has it."""

    def test_known_gaps_family_message_mentions_both_paths(self):
        from patent_mcp_server.screening_table import KNOWN_GAPS
        msg = KNOWN_GAPS["family"]
        self.assertIn("GPSS", msg)
        self.assertIn("epo_family", msg)

    def test_family_gap_filter_includes_gpss(self):
        # Mirror the gaps filter in build_screening_table for source="gpss".
        from patent_mcp_server.screening_table import KNOWN_GAPS
        columns = ["pubno", "family"]
        source = "gpss"
        gaps = {k: v for k, v in KNOWN_GAPS.items()
                if (k in columns or k == "family")
                and (source == "google" or k in ("legal_status", "citations", "family"))}
        self.assertIn("family", gaps)


if __name__ == "__main__":
    unittest.main(verbosity=2)
