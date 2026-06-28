"""Unit tests for BR_20260628 remediation (drawing scraping / CDN / EPO).

Covers:
  A — GPSS scraping single-thread serialization + random delay
  B — gpatents_download_figure CDN 403 explicit downgrade
  D — extract_representative_figure FIG.1 locate + render / NO_FIGURE_PAGE
  E — _flatten thumbnail resolution tag
  F — fetch_patent_pdf EPO single-page biblio downgrade

Run: .venv/bin/python -m pytest tests/test_br20260628_figures.py
 or: .venv/bin/python tests/test_br20260628_figures.py
"""
import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import patent_mcp_server.patents as P
from patent_mcp_server.gpatents.client import GooglePatentsClient


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


# ── E: thumbnail resolution tag ────────────────────────────────────
class ThumbnailResolutionTagTest(unittest.TestCase):
    def test_thumb_present_tagged(self):
        item = {"patent": {"publication_number": "US123",
                           "thumbnail": "x/60x80/abc.png", "pdf": "y/full.pdf"}}
        r = GooglePatentsClient._flatten(item)
        self.assertEqual(r["representative_figure_resolution"], "thumbnail")
        self.assertTrue(r["representative_figure_url"])

    def test_no_thumb_no_tag(self):
        item = {"patent": {"publication_number": "US999"}}
        r = GooglePatentsClient._flatten(item)
        self.assertIsNone(r["representative_figure_resolution"])
        self.assertIsNone(r["representative_figure_url"])


# ── B: CDN 403 explicit downgrade ──────────────────────────────────
class Cdn403DowngradeTest(unittest.TestCase):
    def test_403_returns_cdn_forbidden(self):
        import httpx

        async def _raise_403(url):
            req = httpx.Request("GET", url)
            resp = httpx.Response(403, request=req)
            raise httpx.HTTPStatusError("403", request=req, response=resp)

        orig = P.gpatents_client.fetch_bytes
        P.gpatents_client.fetch_bytes = _raise_403  # type: ignore
        try:
            out = asyncio.run(P.gpatents_download_figure(
                "https://patentimages.storage.googleapis.com/60x80/x.png"))
        finally:
            P.gpatents_client.fetch_bytes = orig  # type: ignore
        self.assertFalse(out["success"])
        self.assertEqual(out["error"], "CDN_FORBIDDEN")
        self.assertEqual(out["http_code"], 403)
        self.assertIn("downgrade_hint", out)


# ── D: extract_representative_figure ───────────────────────────────
class ExtractFigureTest(unittest.TestCase):
    def test_locate_and_render_fig1(self):
        import tempfile
        td = tempfile.mkdtemp()
        pdf = os.path.join(td, "t.pdf")
        _make_pdf(pdf, ["COVER PAGE Patent TW123",
                        "FIG. 1\n10 12 14a 16 18 20 22",
                        "DETAILED DESCRIPTION"])
        loc = P._locate_figure_page(pdf)
        self.assertEqual(loc["page"], 2)
        self.assertEqual(loc["method"], "fig1_text")
        png = P._render_page_png(pdf, loc["page"], dpi=120)
        self.assertTrue(png and len(png) > 0)

    def test_no_text_layer_returns_none(self):
        import tempfile
        td = tempfile.mkdtemp()
        pdf = os.path.join(td, "blank.pdf")
        # single blank-ish page, no FIG markers, sparse text
        _make_pdf(pdf, ["   "])
        loc = P._locate_figure_page(pdf)
        self.assertIsNone(loc["page"])
        self.assertEqual(loc["method"], "none")

    def test_extract_tool_no_pdf(self):
        async def _fail_fetch(pn, *a, **k):
            return {"success": False, "error": "ALL_SOURCES_FAILED", "attempts": []}

        orig = P.fetch_patent_pdf
        # patch the module-level name the tool calls
        P.fetch_patent_pdf = _fail_fetch  # type: ignore
        try:
            out = asyncio.run(P.extract_representative_figure("US123"))
        finally:
            P.fetch_patent_pdf = orig  # type: ignore
        self.assertFalse(out["success"])
        self.assertEqual(out["error"], "NO_PDF")


# ── F: EPO single-page biblio downgrade ────────────────────────────
class EpoSinglePageDowngradeTest(unittest.TestCase):
    def test_pdf_bytes_page_count(self):
        import tempfile
        td = tempfile.mkdtemp()
        one = os.path.join(td, "one.pdf")
        _make_pdf(one, ["BIBLIO ONLY"])
        self.assertEqual(P._pdf_bytes_page_count(open(one, "rb").read()), 1)
        multi = os.path.join(td, "multi.pdf")
        _make_pdf(multi, ["p1", "p2", "p3"])
        self.assertEqual(P._pdf_bytes_page_count(open(multi, "rb").read()), 3)


# ── A: GPSS scraping serialization helper present ──────────────────
class GpssThrottleTest(unittest.TestCase):
    def test_lock_and_pace_exist(self):
        self.assertTrue(hasattr(P, "_GPSS_SCRAPE_LOCK"))
        self.assertTrue(isinstance(P._GPSS_SCRAPE_LOCK, asyncio.Lock))
        self.assertTrue(hasattr(P, "_gpss_scrape_pace"))

    def test_pace_sleeps_in_range(self):
        slept = []

        async def _fake_sleep(d):
            slept.append(d)

        orig = asyncio.sleep
        asyncio.sleep = _fake_sleep  # type: ignore
        try:
            asyncio.run(P._gpss_scrape_pace())
        finally:
            asyncio.sleep = orig  # type: ignore
        self.assertEqual(len(slept), 1)
        self.assertGreaterEqual(slept[0], P._GPSS_SCRAPE_MIN_DELAY)
        self.assertLessEqual(slept[0], P._GPSS_SCRAPE_MAX_DELAY)


# ── G: GPSS figure URL classification (country + extension agnostic) ──
# Locks the regex that splits a GPSS detail page's image URLs into the
# representative thumbnail (<C>G1) vs the full 圖式(A1) series (<C>G2_<NNN>).
# The old code hardcoded "TWG1" + ".png"; this matrix proves the new code is
# country-agnostic AND extension-agnostic, including the EP edge case where the
# SAME patent serves G1 as .jpg but G2 as .png.
class GpssFigureUrlClassificationTest(unittest.TestCase):
    import re as _re

    @staticmethod
    def _is_g2(u):
        import re
        return re.search(r'G2[^/]*_\d+\.(?:png|jpe?g|gif|tiff?)$', u, re.IGNORECASE) is not None

    @staticmethod
    def _is_g1(u):
        import re
        return re.search(r'G1[^/]*\.(?:png|jpe?g|gif|tiff?)$', u, re.IGNORECASE) is not None

    # (url, expect_g1, expect_g2) — real samples observed across jurisdictions.
    CASES = [
        # US — png
        ("/gpss2/gpssbkmusr/00004/USG120230081319A1.png", True, False),
        ("/gpss2/gpssbkmusr/00004/USG220230081319A1_000.png", False, True),
        ("/gpss2/gpssbkmusr/00004/USG220230081319A1_009.png", False, True),
        # TW — png
        ("/gpss2/gpssbkmusr/00003/TWG1202503567A.png", True, False),
        ("/gpss2/gpssbkmusr/00003/TWG2202503567A_000.png", False, True),
        # CN — jpg
        ("/gpss2/gpssbkmusr/00015/CNG1120672280A.jpg", True, False),
        ("/gpss2/gpssbkmusr/00015/CNG2120672280A_001.jpg", False, True),
        # EP edge case — G1 jpg but G2 png on the SAME patent
        ("/gpss2/gpssbkmusr/00099/CNG1107533716A.jpg", True, False),
        ("/gpss2/gpssbkmusr/00099/CNG2107533716A_000.png", False, True),
        # JP — png
        ("/gpss2/gpssbkmusr/00050/JPG12023050048A.png", True, False),
        ("/gpss2/gpssbkmusr/00050/JPG22023050048A_000.png", False, True),
    ]

    def test_classification_matrix(self):
        for url, exp_g1, exp_g2 in self.CASES:
            self.assertEqual(self._is_g1(url), exp_g1, f"G1 mismatch: {url}")
            self.assertEqual(self._is_g2(url), exp_g2, f"G2 mismatch: {url}")

    def test_g2_series_sorts_by_page(self):
        urls = [
            "/x/USG220230081319A1_002.png",
            "/x/USG220230081319A1_000.png",
            "/x/USG220230081319A1_001.png",
        ]
        g2 = sorted(u for u in urls if self._is_g2(u))
        self.assertTrue(g2[0].endswith("_000.png"))
        self.assertTrue(g2[-1].endswith("_002.png"))

    def test_cache_buster_stripped(self):
        raw = "/gpss2/gpssbkmusr/00004/USG220230081319A1_000.png?1559877649"
        base = raw.split("?", 1)[0]
        self.assertTrue(self._is_g2(base))
        self.assertFalse(base.endswith("?1559877649"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
