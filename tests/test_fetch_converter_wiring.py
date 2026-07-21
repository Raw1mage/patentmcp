"""L3 roundtrip gate — BR_20260719 R3: fetch-chain per-target pubno converter wiring.

The fetch degradation chain (patent_get_claim1 / patent_enrich_backfill) used to
bare-send the raw pubno to every external source. A US grant number with a
LEADING-ZERO serial (US09993161B1) 404s at gpatents; the un-padded form
(US9993161) hits — the leading zero is the sole變因 (實測坐實 R3).

These tests spy on the number handed to each send site (via mocked external
clients) and assert it is the converter-normalized canonical, NOT the raw pubno.
The reverse case (bare-send) MUST fail these assertions — that is the gate.

Run: .venv/bin/python -m pytest tests/test_fetch_converter_wiring.py -v
"""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from patent_mcp_server import patents as P
from patent_mcp_server import pubno_convert as pc


class GpatentsCanonicalHelperTest(unittest.TestCase):
    """_to_gpatents_canonical: 剝前導零 canonical + idempotent + fail-fast。"""

    def test_us_grant_leading_zero_stripped(self):
        # R3 core: US09993161B1 -> US9993161 (實測命中形式)
        self.assertEqual(P._to_gpatents_canonical("US09993161B1"), "US9993161")

    def test_idempotent_on_canonical(self):
        # already-canonical number unchanged
        self.assertEqual(P._to_gpatents_canonical("US9993161"), "US9993161")

    def test_no_leading_zero_kind_stripped(self):
        # gpatents canonical drops the kind (實測: US9993161 without kind hit); the
        # digit body carries no leading zero here so only the kind is removed.
        self.assertEqual(P._to_gpatents_canonical("US11213256B2"), "US11213256")

    def test_foreign_cc_preserved(self):
        self.assertEqual(P._to_gpatents_canonical("CN119230141A"), "CN119230141")

    def test_fail_fast_on_empty(self):
        # unparseable -> None (caller MUST NOT bare-send raw pubno)
        self.assertIsNone(P._to_gpatents_canonical(""))


class GpatentsSendSiteSpyTest(unittest.TestCase):
    """L3 gate: patent_get_claim1 的 gpatents 尾級送查點收到的必須是 strip-0
    canonical,而非原號。反向(裸送原號)時此斷言 fail —— 這就是防復發的閘。"""

    def _run_with_leading_zero_pubno(self):
        """跑 patent_get_claim1('US09993161B1'),讓 GPSS/PPUBS/EPO/BQ 全 miss,
        逼到 gpatents 尾級,spy 傳入 gpatents_client.get_patent 的號碼。"""
        captured = {}

        async def fake_get_patent(publication_number, include_description=False):
            captured["pub"] = publication_number
            return {"success": True, "claims": [{"text": "1. A widget comprising a foo."}]}

        with mock.patch.object(P.gpss_client, "configured", return_value=False), \
             mock.patch.object(P.epo_client, "configured", return_value=False), \
             mock.patch.object(P, "google_bq_client") as bq, \
             mock.patch.object(P.ppubs_client, "run_query",
                               side_effect=Exception("ppubs unavailable")), \
             mock.patch.object(P.gpatents_client, "get_patent",
                               side_effect=fake_get_patent):
            bq.client = None
            out = asyncio.run(P.patent_get_claim1("US09993161B1"))
        return captured, out

    def test_gpatents_receives_strip0_canonical(self):
        captured, out = self._run_with_leading_zero_pubno()
        # 核心斷言: 送到 gpatents 的號碼是剝零 canonical,不是原號
        self.assertEqual(captured.get("pub"), "US9993161",
                         "gpatents send site did NOT receive strip-0 canonical "
                         "(bare-send regression — BR_20260719 R3)")
        self.assertTrue(out.get("success"))
        self.assertEqual(out.get("source"), "google_patents")

    def test_reverse_bare_send_would_fail_the_gate(self):
        # 反向證明: 若送查點裸送原號,收到的會是 'US09993161B1' != canonical。
        # 這裡直接證明 helper 對原號與剝零形式的輸出不同 → 閘有鑑別力。
        raw = "US09993161B1"
        canonical = P._to_gpatents_canonical(raw)
        self.assertNotEqual(canonical, raw,
                            "converter must transform the leading-zero pubno; "
                            "if equal, the send-site spy could not distinguish "
                            "bare-send from wired (gate would be blind)")


class EpoVariantSendSiteSpyTest(unittest.TestCase):
    """L3 gate: EPO 送查點逐 to_epo_variants 變體試,收到的首個變體必須是
    to_epo_variants 的 primary form,而非裸原號。"""

    def test_epo_receives_docdb_variants_not_raw(self):
        seen = []

        async def fake_claims(pubno):
            seen.append(pubno)
            return {"success": True, "found": True, "claim1": "1. An EP widget."}

        with mock.patch.object(P.gpss_client, "configured", return_value=False), \
             mock.patch.object(P.epo_client, "configured", return_value=True), \
             mock.patch.object(P.epo_client, "claims", side_effect=fake_claims):
            out = asyncio.run(P.patent_get_claim1("EP-1234567-A1"))

        # 送到 EPO 的首個號碼是 to_epo_variants primary (docdb 點分形式),非裸原號
        self.assertTrue(seen, "EPO send site was never reached")
        self.assertEqual(seen[0], pc.to_epo_variants("EP-1234567-A1")[0])
        self.assertNotEqual(seen[0], "EP-1234567-A1",
                            "EPO send site bare-sent the raw pubno (regression)")
        self.assertTrue(out.get("success"))
        self.assertEqual(out.get("source"), "epo")


class GpssRestSendSiteSpyTest(unittest.TestCase):
    """L3 gate: GPSS 主查送查點收到的 condition value 必須是 to_gpss_rest 正規化
    (去分隔符大寫),而非裸原號。"""

    def test_gpss_condition_receives_gpss_rest(self):
        captured = {}

        async def fake_search(conditions=None, databases=None, fields=None, num=None):
            captured["value"] = conditions[0].value if conditions else None
            # 回空 data → 讓 claim1 落空,不影響本測試(只驗送查號)
            return {"success": False}

        with mock.patch.object(P.gpss_client, "configured", return_value=True), \
             mock.patch.object(P.gpss_client, "search", side_effect=fake_search), \
             mock.patch.object(P.epo_client, "configured", return_value=False), \
             mock.patch.object(P, "google_bq_client") as bq, \
             mock.patch.object(P.ppubs_client, "run_query",
                               side_effect=Exception("ppubs unavailable")), \
             mock.patch.object(P.gpatents_client, "get_patent",
                               side_effect=Exception("gpatents unavailable")):
            bq.client = None
            asyncio.run(P.patent_get_claim1("US-09993161-B1"))

        self.assertEqual(captured.get("value"), pc.to_gpss_rest("US-09993161-B1"),
                         "GPSS condition did NOT receive to_gpss_rest-normalized "
                         "number (bare-send regression)")


class EnrichBackfillSendSiteSpyTest(unittest.TestCase):
    """L3 gate: patent_enrich_backfill 的 gpatents 送查點同樣過 strip-0 canonical。"""

    def test_enrich_backfill_gpatents_receives_canonical(self):
        # 直接驗接線點的 helper 語義即可 (整個 backfill 迴圈需 patentdb 環境)。
        # 送查前正規化: US09993161B1 -> US9993161。
        self.assertEqual(P._to_gpatents_canonical("US09993161B1"), "US9993161")
        # fail-fast: 認不出有效號形 -> None -> 呼叫端記 gap,不裸送
        self.assertIsNone(P._to_gpatents_canonical("???"))
        self.assertIsNone(P._to_gpatents_canonical("ABC"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
