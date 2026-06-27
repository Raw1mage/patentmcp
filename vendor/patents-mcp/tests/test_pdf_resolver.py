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


class GpssPdfDownloadTest(unittest.TestCase):
    def test_gpss_pdf_download_success(self):
        from patent_mcp_server.patents import gpss_download_patent_pdf
        # TWI854998B is a valid TW patent
        out = asyncio.run(gpss_download_patent_pdf("TWI854998B"))
        self.assertTrue(out.get("success"), f"Download failed: {out.get('error')}")
        self.assertIn("token", out)
        self.assertIn("sha256", out)

    def test_gpss_pdf_download_normalization(self):
        from patent_mcp_server.patents import gpss_download_patent_pdf
        # Test with spaces and lowercase TW, e.g. "tw I854998 b"
        out = asyncio.run(gpss_download_patent_pdf("tw I854998 b"))
        self.assertTrue(out.get("success"), f"Download failed: {out.get('error')}")

    def test_gpss_xml_download(self):
        from patent_mcp_server.patents import gpss_download_patent_xml
        # Test downloading TWI854998B xml format
        out = asyncio.run(gpss_download_patent_xml("TWI854998B"))
        self.assertTrue(out.get("success"), f"Download failed: {out.get('error')}")
        self.assertIn("token", out)
        self.assertIn("sha256", out)
        
        from patent_mcp_server.patents import token_store
        entry = token_store.resolve(out["token"])
        content = entry.file_path.read_bytes()
        self.assertTrue(content.startswith(b"<?xml") or content.startswith(b"\xef\xbb\xbf<?xml"))

    def test_local_cache_priority(self):
        import shutil
        from pathlib import Path
        from patent_mcp_server.patents import fetch_patent_pdf, gpss_download_patent_xml, token_store
        
        # Define fake patent path
        db_root = Path(__file__).resolve().parent.parent.parent.parent / "patentdb"
        fake_dir = db_root / "TW" / "FAKE12345"
        
        # Clean up any existing fake dir
        shutil.rmtree(fake_dir, ignore_errors=True)
        fake_dir.mkdir(parents=True, exist_ok=True)
        
        pdf_content = b"%PDF-1.4 fake pdf content"
        xml_content = b"<?xml version=\"1.0\" encoding=\"UTF-8\"?><fake_xml></fake_xml>"
        
        try:
            # 1. Write fake cache files
            (fake_dir / "specification.pdf").write_bytes(pdf_content)
            (fake_dir / "specification.xml").write_bytes(xml_content)
            
            # 2. Test fetch_patent_pdf cache HIT
            out_pdf = asyncio.run(fetch_patent_pdf("TWFAKE12345"))
            self.assertTrue(out_pdf.get("success"))
            self.assertEqual(out_pdf.get("source"), "local_cache")
            
            entry_pdf = token_store.resolve(out_pdf["token"])
            self.assertEqual(entry_pdf.file_path.read_bytes(), pdf_content)
            
            # 3. Test gpss_download_patent_xml cache HIT
            out_xml = asyncio.run(gpss_download_patent_xml("TWFAKE12345"))
            self.assertTrue(out_xml.get("success"))
            
            entry_xml = token_store.resolve(out_xml["token"])
            self.assertEqual(entry_xml.file_path.read_bytes(), xml_content)
            
        finally:
            # Clean up
            shutil.rmtree(fake_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
