"""Offline unit tests for patent-pdf-fetch: citation_pdf_url parser + source routing.

Run: .venv/bin/python -m pytest tests/test_pdf_resolver.py   (if pytest present)
 or: .venv/bin/python tests/test_pdf_resolver.py             (stdlib fallback)
"""
import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from patent_mcp_server.gpatents.client import GooglePatentsClient


REAL_META = (
    '<head><meta name="citation_pdf_url" '
    'content="https://patentimages.storage.googleapis.com/2f/2b/90/'
    'f66567bc6e4afe/TWI854998B.pdf"></head>'
)
GUESSED_META = (
    '<head><meta name="citation_pdf_url" '
    'content="https://patentimages.storage.googleapis.com/pdfs/US123.pdf">'
    '</head>'
)
NO_META = "<head><title>no pdf here</title></head>"


class ExtractPdfUrlTest(unittest.TestCase):
    def test_extracts_real_hashed_url(self):
        url = GooglePatentsClient._extract_pdf_url(REAL_META)
        self.assertEqual(
            url,
            "https://patentimages.storage.googleapis.com/2f/2b/90/"
            "f66567bc6e4afe/TWI854998B.pdf",
        )

    def test_rejects_guessed_pdfs_path(self):
        # /pdfs/<short>.pdf is the known-wrong guessed shape → must be rejected
        self.assertIsNone(GooglePatentsClient._extract_pdf_url(GUESSED_META))

    def test_returns_none_when_no_meta(self):
        self.assertIsNone(GooglePatentsClient._extract_pdf_url(NO_META))


class ResolvePdfUrlRoutingTest(unittest.TestCase):
    def test_not_found_maps_structured_error(self):
        client = GooglePatentsClient()

        class _Resp:
            text = NO_META

        async def _fake_get(url):
            return _Resp()

        client._get = _fake_get  # type: ignore[assignment]
        out = asyncio.run(client.resolve_pdf_url("US123A"))
        self.assertFalse(out["success"])
        self.assertEqual(out["error"], "NOT_FOUND")

    def test_success_returns_pdf_url(self):
        client = GooglePatentsClient()

        class _Resp:
            text = REAL_META

        async def _fake_get(url):
            return _Resp()

        client._get = _fake_get  # type: ignore[assignment]
        out = asyncio.run(client.resolve_pdf_url("TWI854998B"))
        self.assertTrue(out["success"])
        self.assertIn("TWI854998B.pdf", out["pdf_url"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
