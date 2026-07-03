"""Tests for the patent_search source-ladder dispatcher.

Covers test-vectors.json TV-1 ~ TV-8 (plans/patentmcp_search-dispatcher):
monkeypatched clients, no real network. Pattern follows
test_br20260628_tooling_gaps.py (direct async tool-fn calls via asyncio.run).

Run: uv run pytest tests/test_search_dispatcher.py -q
"""
import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import patent_mcp_server.patents as P
import patent_mcp_server.search_dispatcher as SD


# ── fake clients ────────────────────────────────────────────────────

def _gpss_hit_payload(pubs):
    return {
        "success": True, "status": "success", "message": None,
        "total": len(pubs), "qty": len(pubs),
        "data": {"gpss-API": {"patent": {"patentcontent": [
            {
                "publication-reference": {"doc-number": p},
                "patent-title": {"english-title": f"Title {p}"},
                "claims": {"claim": [{"claim-text": "1. A device."}]},
            } for p in pubs
        ]}}},
    }


class FakeGPSS:
    def __init__(self, configured=True, pubs=None, fail=False):
        self._configured = configured
        self.pubs = pubs or []
        self.fail = fail
        self.calls = 0

    def configured(self):
        return self._configured

    async def search(self, **kwargs):
        self.calls += 1
        if self.fail:
            return {"success": False, "error": "GPSS 500 boom"}
        if not self.pubs:
            return {"success": False, "status": "success",
                    "message": "no record found", "total": 0}
        return _gpss_hit_payload(self.pubs)


class FakeEPO:
    def __init__(self, configured=True, pubs=None):
        self._configured = configured
        self.pubs = pubs or []
        self.calls = 0

    def configured(self):
        return self._configured

    async def search(self, cql, range_="1-25"):
        self.calls += 1
        return {"success": True, "cql": cql, "total": len(self.pubs),
                "count": len(self.pubs), "results": list(self.pubs)}

    async def biblio(self, pub):
        return {"success": True, "pub": pub, "found": True,
                "title": f"EPO title {pub}", "abstract": "abs",
                "applicants": ["ACME"], "ipc": ["A61B5/024"]}


class FakePPUBS:
    def __init__(self, docs=None, error=False):
        self.docs = docs or []
        self.error = error
        self.calls = 0

    async def run_query(self, **kwargs):
        self.calls += 1
        if self.error:
            return {"error": True, "message": "ppubs down"}
        return {"patents": list(self.docs), "totalResults": len(self.docs)}


class FakeGPatents:
    def __init__(self, results=None):
        self.results = results or []
        self.calls = 0

    async def search(self, **kwargs):
        self.calls += 1
        return {"success": True, "total_num_results": len(self.results),
                "results": list(self.results)}


def _dispatch(spec_kwargs, gpss=None, epo=None, ppubs=None, gpat=None):
    spec = SD.normalize_query(**spec_kwargs)
    return asyncio.run(SD.dispatch_search(
        spec,
        gpss_client=gpss or FakeGPSS(),
        epo_client=epo or FakeEPO(),
        ppubs_client=ppubs or FakePPUBS(),
        gpatents_client=gpat or FakeGPatents(),
    ))


def _prov(out):
    return {p["source"]: p for p in out["provenance"]}


# ── TV-1: GPSS configured + cpc/keyword → GPSS hit, EPO/PPUBS skipped ──
class TV1GpssPrimaryHit(unittest.TestCase):
    def test_gpss_hit_others_skipped(self):
        gpss = FakeGPSS(configured=True, pubs=["US1", "US2"])
        epo, ppubs = FakeEPO(), FakePPUBS()
        out = _dispatch({"cpc": "G06Q50/18", "keyword": "patent search", "num": 5},
                        gpss=gpss, epo=epo, ppubs=ppubs)
        self.assertTrue(out["success"])
        self.assertEqual(out["source"], "gpss")
        prov = _prov(out)
        self.assertEqual(prov["gpss"]["status"], "hit")
        self.assertEqual(prov["epo"]["status"], "skipped")
        self.assertEqual(prov["ppubs"]["status"], "skipped")
        self.assertEqual(epo.calls, 0)
        self.assertEqual(ppubs.calls, 0)
        self.assertEqual(out["records"][0]["pubno"], "US1")
        self.assertTrue(out["gaps"])  # honest gaps present


# ── TV-2: GPSS not configured → EPO search→biblio second stage ──
class TV2EpoFallback(unittest.TestCase):
    def test_epo_two_stage(self):
        gpss = FakeGPSS(configured=False)
        epo = FakeEPO(configured=True, pubs=["EP1234567A1"])
        out = _dispatch({"cpc": "G06Q50/18"}, gpss=gpss, epo=epo)
        self.assertTrue(out["success"])
        self.assertEqual(out["source"], "epo")
        prov = _prov(out)
        self.assertEqual(prov["gpss"]["status"], "skipped")
        self.assertEqual(prov["gpss"]["reason"], "not_configured")
        self.assertEqual(prov["epo"]["status"], "hit")
        self.assertEqual(gpss.calls, 0)
        rec = out["records"][0]
        self.assertEqual(rec["pubno"], "EP1234567A1")
        self.assertEqual(rec["title"], "EPO title EP1234567A1")
        self.assertEqual(rec["claim1"], "")  # honest blank

    def test_epo_biblio_truncated_note(self):
        pubs = [f"EP{i:07d}A1" for i in range(20)]  # > EPO_BIBLIO_MAX
        epo = FakeEPO(configured=True, pubs=pubs)
        out = _dispatch({"cpc": "G06Q50/18", "num": 20},
                        gpss=FakeGPSS(configured=False), epo=epo)
        self.assertTrue(out["success"])
        prov = _prov(out)
        self.assertEqual(prov["epo"]["reason"], "biblio_truncated")
        self.assertEqual(len(out["records"]), SD.EPO_BIBLIO_MAX)


# ── TV-3: USPC axis → direct PPUBS, GPSS/EPO skipped axis_unsupported ──
class TV3UspcDirectPpubs(unittest.TestCase):
    def test_uspc_routes_to_ppubs(self):
        gpss = FakeGPSS(configured=True, pubs=["USX"])
        ppubs = FakePPUBS(docs=[{
            "publicationReferenceDocumentNumber": "US9999999",
            "inventionTitle": "USPC hit",
            "applicationNumberText": "12/345678",
        }])
        out = _dispatch({"uspc": "705/300"}, gpss=gpss, ppubs=ppubs)
        self.assertTrue(out["success"])
        self.assertEqual(out["source"], "ppubs")
        prov = _prov(out)
        self.assertEqual(prov["gpss"]["status"], "skipped")
        self.assertEqual(prov["gpss"]["reason"], "axis_unsupported")
        self.assertEqual(prov["epo"]["status"], "skipped")
        self.assertEqual(prov["epo"]["reason"], "axis_unsupported")
        self.assertEqual(prov["ppubs"]["status"], "hit")
        self.assertEqual(gpss.calls, 0)
        self.assertEqual(out["records"][0]["pubno"], "US9999999")


# ── TV-4: all official miss + allow_scraping=False → SCRAPING_REQUIRED ──
class TV4ScrapingGate(unittest.TestCase):
    def test_scraping_required_gpatents_not_called(self):
        gpat = FakeGPatents(results=[{"publication_number": "USZZZ"}])
        out = _dispatch({"keyword": "obscure query", "allow_scraping": False},
                        gpss=FakeGPSS(pubs=[]), epo=FakeEPO(pubs=[]),
                        ppubs=FakePPUBS(docs=[]), gpat=gpat)
        self.assertFalse(out["success"])
        self.assertEqual(out["error_code"], "SCRAPING_REQUIRED")
        self.assertEqual(gpat.calls, 0)
        prov = _prov(out)
        # official three levels recorded as miss; gpatents skipped + scraping flag
        for s in ("gpss", "epo", "ppubs"):
            self.assertEqual(prov[s]["status"], "miss")
        self.assertEqual(prov["gpatents"]["status"], "skipped")
        self.assertEqual(prov["gpatents"]["reason"], "scraping_not_authorized")
        self.assertTrue(prov["gpatents"]["scraping"])


# ── TV-5: all official miss + allow_scraping=True → gpatents tail ──
class TV5AuthorizedTail(unittest.TestCase):
    def test_gpatents_tail_hit(self):
        gpat = FakeGPatents(results=[{
            "publication_number": "US7777777", "title": "tail hit",
            "snippet": "snip",
        }])
        out = _dispatch({"keyword": "obscure query", "allow_scraping": True},
                        gpss=FakeGPSS(pubs=[]), epo=FakeEPO(pubs=[]),
                        ppubs=FakePPUBS(docs=[]), gpat=gpat)
        self.assertTrue(out["success"])
        self.assertEqual(out["source"], "gpatents")
        last = out["provenance"][-1]
        self.assertEqual(last["source"], "gpatents")
        self.assertEqual(last["status"], "hit")
        self.assertTrue(last["scraping"])
        self.assertEqual(gpat.calls, 1)


# ── TV-6: everything misses (scraping authorized) → ALL_SOURCES_MISS ──
class TV6AllSourcesMiss(unittest.TestCase):
    def test_all_miss_full_provenance(self):
        out = _dispatch({"keyword": "impossible", "allow_scraping": True},
                        gpss=FakeGPSS(pubs=[]), epo=FakeEPO(pubs=[]),
                        ppubs=FakePPUBS(docs=[]), gpat=FakeGPatents(results=[]))
        self.assertFalse(out["success"])
        self.assertEqual(out["error_code"], "ALL_SOURCES_MISS")
        self.assertEqual(len(out["provenance"]), 4)


# ── TV-7: no search axis → INVALID_PARAMS, zero backend calls ──
class TV7InvalidParams(unittest.TestCase):
    def test_invalid_params_no_backend(self):
        gpss, epo, ppubs, gpat = FakeGPSS(), FakeEPO(), FakePPUBS(), FakeGPatents()
        out = _dispatch({}, gpss=gpss, epo=epo, ppubs=ppubs, gpat=gpat)
        self.assertFalse(out["success"])
        self.assertEqual(out["error_code"], "INVALID_PARAMS")
        self.assertEqual(gpss.calls + epo.calls + ppubs.calls + gpat.calls, 0)
        self.assertEqual(out["provenance"], [])


# ── TV-8: uspto_patents legacy search methods rejected ──
class TV8UsptoSearchRetired(unittest.TestCase):
    def test_search_patents_rejected(self):
        out = asyncio.run(P.uspto_patents(
            method="ppubs_search_patents", query="CCL/705/300"))
        self.assertFalse(out["success"])
        self.assertIn("patent_search", out["message"])

    def test_search_applications_rejected(self):
        out = asyncio.run(P.uspto_patents(
            method="ppubs_search_applications", query="x"))
        self.assertFalse(out["success"])
        self.assertIn("patent_search", out["message"])


# ── backend error → provenance error entry, ladder continues ──
class BackendErrorContinues(unittest.TestCase):
    def test_gpss_error_falls_through_to_epo(self):
        gpss = FakeGPSS(configured=True, fail=True)
        epo = FakeEPO(configured=True, pubs=["EP1A1"])
        out = _dispatch({"cpc": "G06Q50/18"}, gpss=gpss, epo=epo)
        self.assertTrue(out["success"])
        self.assertEqual(out["source"], "epo")
        prov = _prov(out)
        self.assertEqual(prov["gpss"]["status"], "error")
        self.assertEqual(prov["gpss"]["reason"], "http_error:500")


# ── patent_search MCP tool wires module clients into the dispatcher ──
class PatentSearchToolWiring(unittest.TestCase):
    def test_tool_uses_module_singletons(self):
        orig = (P.gpss_client, P.epo_client, P.ppubs_client, P.gpatents_client)
        gpss = FakeGPSS(configured=True, pubs=["TW111"])
        P.gpss_client, P.epo_client = gpss, FakeEPO()  # type: ignore
        P.ppubs_client, P.gpatents_client = FakePPUBS(), FakeGPatents()  # type: ignore
        try:
            out = asyncio.run(P.patent_search(cpc="G06Q50/18"))
        finally:
            (P.gpss_client, P.epo_client, P.ppubs_client, P.gpatents_client) = orig  # type: ignore
        self.assertTrue(out["success"])
        self.assertEqual(out["source"], "gpss")
        self.assertEqual(out["records"][0]["pubno"], "TW111")


# ── build_screening_table is LANDED (R13): now a TOOL_LANDED redirect stub ──
# The screening-table build is a deterministic record→CSV transform that runs in
# skills/patentworks/scripts/screening_build.py; the container tool only redirects.
class ScreeningTableLandedStub(unittest.TestCase):
    def test_returns_tool_landed_envelope(self):
        out = asyncio.run(P.build_screening_table(cpc="G06Q50/18", num=5, max_rows=5))
        self.assertFalse(out["success"])
        self.assertEqual(out["error_code"], "TOOL_LANDED")
        self.assertEqual(out["landing"]["script"],
                         "skills/patentworks/scripts/screening_build.py")
        self.assertIn("screening_build.py", out["landing"]["usage"])

    def test_stub_issues_no_search(self):
        # A stub must NOT touch the dispatcher/scraper at all.
        orig = (P.gpss_client, P.epo_client, P.ppubs_client, P.gpatents_client)
        gpat = FakeGPatents(results=[{"publication_number": "USX"}])
        P.gpss_client = FakeGPSS(configured=True, pubs=[])  # type: ignore
        P.epo_client = FakeEPO(configured=True, pubs=[])  # type: ignore
        P.ppubs_client, P.gpatents_client = FakePPUBS(docs=[]), gpat  # type: ignore
        try:
            out = asyncio.run(P.build_screening_table(keyword="obscure", num=5, max_rows=5))
        finally:
            (P.gpss_client, P.epo_client, P.ppubs_client, P.gpatents_client) = orig  # type: ignore
        self.assertEqual(out["error_code"], "TOOL_LANDED")
        self.assertEqual(gpat.calls, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
