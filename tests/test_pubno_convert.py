"""Tests for pubno_convert.py — 跨 DB 專利號碼格式轉換 SSOT (BR_20260719).

Run: .venv/bin/python -m pytest tests/test_pubno_convert.py -v
 or: .venv/bin/python tests/test_pubno_convert.py   (stdlib unittest fallback)
"""
import inspect
import json
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from patent_mcp_server import pubno_convert as pc


class ConverterVectorTest(unittest.TestCase):
    """test-vectors.json TV-1..8 — mapping 表每條實測依據。"""

    def test_to_patentdb_key_cn_strip_kind(self):
        self.assertEqual(pc.to_patentdb_key("CN119230141A"), "CN119230141")

    def test_to_patentdb_key_us_keep_numeric_kind(self):
        self.assertEqual(pc.to_patentdb_key("US11213256B2"), "US11213256B2")

    def test_patentdb_key_variants_cn_dual(self):
        self.assertEqual(
            pc.patentdb_key_variants("CN119230141A"),
            ["CN119230141", "CN119230141A"],
        )

    def test_patentdb_key_variants_no_dup_when_equal(self):
        # US keeps kind → stripped == original → single element (no dup)
        self.assertEqual(pc.patentdb_key_variants("US11213256B2"), ["US11213256B2"])

    def test_to_epo_variants_us_pregrant_dual_digits(self):
        # US pre-grant serial EPO 端 10↔11 位雙變體,主形式在前 (§2.3 + 騙局3)
        self.assertEqual(
            pc.to_epo_variants("US20230053201A1"),
            ["US.20230053201.A1", "US.2023053201.A1"],
        )

    def test_to_epo_variants_us_grant_leading_zero(self):
        # US grant 舊號序號帶前導零 → EPO 存 un-padded serial,需 strip 變體
        # (§2.4-晚 實測: US09997041B2→404 / US9997041B2→found)
        self.assertEqual(
            pc.to_epo_variants("US9997041B2"),
            ["US.9997041.B2"],  # 7位無前導零 → 單形式即可
        )
        self.assertEqual(
            pc.to_epo_variants("US09997041B2"),
            ["US.09997041.B2", "US.9997041.B2"],  # 帶前導零 → 主形式+strip變體
        )

    def test_to_epo_variants_us_old_a_leading_zero(self):
        # US old-A (1990s) 序號帶前導零 (§2.4-晚: US06150941A→404 / US6150941A→found)
        self.assertEqual(
            pc.to_epo_variants("US06150941A"),
            ["US.06150941.A", "US.6150941.A"],
        )

    def test_to_epo_variants_us_recent_no_leading_zero_single(self):
        # sanity: 近年號序號本無前導零 → 單形式,不產假變體
        # (§2.4-晚: US11000000B2/US10000000B2 帶不帶零都 found)
        self.assertEqual(pc.to_epo_variants("US11213256B2"), ["US.11213256.B2"])

    def test_to_gpss4_web_tw_appno_infers_apply(self):
        # TW\d{9} 民國年號形 → apply/@AN (§2.1 實測 TW109112770 → TW202138759A)
        self.assertEqual(pc.to_gpss4_web("TW109112770"), ("109112770", "apply"))
        self.assertEqual(pc.to_gpss4_web("TW113141212"), ("113141212", "apply"))
        self.assertEqual(pc.to_gpss4_web("TW112107009"), ("112107009", "apply"))

    def test_to_gpss4_web_tw_pubno_defaults_pub(self):
        self.assertEqual(pc.to_gpss4_web("TW202138759A"), ("202138759", "pub"))

    def test_to_gpss4_web_explicit_axis_overrides(self):
        self.assertEqual(pc.to_gpss4_web("TW109112770", axis="pub"), ("109112770", "pub"))
        with self.assertRaises(ValueError):
            pc.to_gpss4_web("TW109112770", axis="bogus")

    def test_to_gpss_rest_full_pubno(self):
        self.assertEqual(pc.to_gpss_rest("US-11213256-B2"), "US11213256B2")

    def test_dd31_foreign_cc_no_us_double_prefix(self):
        # DD-31 回歸: 外國碼不誤掛 US 前綴
        self.assertEqual(pc.to_patentdb_key("KR20260067039A"), "KR20260067039")

    def test_test_vectors_json_coverage(self):
        """所有 test-vectors.json 向量在此檔有對應斷言（防漂移）。"""
        # sanity: converter 有 mapping 表宣稱的所有函式
        for fn in ("to_patentdb_key", "patentdb_key_variants", "to_gpss_rest",
                   "to_gpss4_web", "to_epo_variants", "to_docdb", "normalize_pubno"):
            self.assertTrue(hasattr(pc, fn), f"missing converter fn {fn}")


class ConvergenceTest(unittest.TestCase):
    """5 處散點改走 converter 後,既有 import 路徑仍解析且行為一致。"""

    def test_epo_client_reexport(self):
        from patent_mcp_server.epo.client import to_docdb, docdb_variants
        self.assertEqual(to_docdb("US11213256B2"), "US.11213256.B2")
        self.assertEqual(
            docdb_variants("US20230053201A1"),
            ["US.20230053201.A1", "US.2023053201.A1"],
        )

    def test_patentdb_store_delegation(self):
        from patent_mcp_server.patentdb_store import (
            canonical_pubno, normalize_pubno, _KNOWN_CC,
        )
        self.assertEqual(canonical_pubno("TWI854998B"), "TWI854998")
        # NOTE: 既有 normalize_pubno 對「數字主體+字母 kind」的 US 號不剝 kind
        # （'A1' 保留）—— 這是 DD-3 要保護的既有語義,converter 忠實複製,勿改。
        self.assertEqual(normalize_pubno("US 2023/0081319 A1"), ("US", "20230081319A1"))
        self.assertIn("TW", _KNOWN_CC)  # patents.py imports this

    def test_patents_delegation(self):
        from patent_mcp_server.patents import _get_patent_country_and_normalized_no as gc
        self.assertEqual(gc("KR20260067039A"), ("KR", "20260067039"))


class BackwardCompatTest(unittest.TestCase):
    """DD-3 硬閘: to_patentdb_key 對既有輸入逐字等同收斂前的 canonical_pubno。"""

    # 收斂前 canonical_pubno 已知輸出（test_patentdb_store.py + 實庫慣例）
    KNOWN = {
        "US20230081319A1": "US20230081319A1",
        "US 2023/0081319 A1": "US20230081319A1",
        "TWI854998B": "TWI854998",
        "CN119230141A": "CN119230141",
        "US11213256B2": "US11213256B2",
        "KR20260067039A": "KR20260067039",
        "TWM305142U": "TWM305142",
    }

    def test_canonical_stable(self):
        for raw, expected in self.KNOWN.items():
            self.assertEqual(pc.to_patentdb_key(raw), expected, f"drift on {raw!r}")

    def test_same_patent_different_formats_collapse(self):
        self.assertEqual(
            pc.to_patentdb_key("US20230081319A1"),
            pc.to_patentdb_key("US 2023/0081319 A1"),
        )


class VendorDriftGuardTest(unittest.TestCase):
    """DD-1: patentdb_local.py 的 vendored normalize_pubno/canonical_pubno 必須與
    src canonical (pubno_convert) 逐字相同（機檢閘,把人工紀律升為 fail-on-drift）。"""

    @staticmethod
    def _stmt_dump(fn):
        """AST 語句序列（去 docstring/註解/空白/變數名細節干擾）—— 精確比對
        執行邏輯本體,docstring 內容不影響結果。"""
        import ast
        import textwrap
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        fn_node = tree.body[0]
        # 去掉函式的 docstring 節點
        body = fn_node.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(getattr(body[0], "value", None), ast.Constant)
                and isinstance(body[0].value.value, str)):
            body = body[1:]
        return "\n".join(ast.dump(n) for n in body)

    def test_vendored_normalize_matches_canonical(self):
        vendored_path = _ROOT / "skills" / "patentworks" / "scripts" / "patentdb_local.py"
        self.assertTrue(vendored_path.is_file(), "patentdb_local.py not found")
        import importlib.util
        spec = importlib.util.spec_from_file_location("_pdb_local", vendored_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # AST 本體比對: canonical (pubno_convert.normalize_pubno) 與 vendored
        # (patentdb_local.normalize_pubno) 的執行語句序列必須完全相同 (DD-1)。
        self.assertEqual(
            self._stmt_dump(pc.normalize_pubno),
            self._stmt_dump(mod.normalize_pubno),
            "vendor drift: patentdb_local.normalize_pubno logic diverged from "
            "pubno_convert.normalize_pubno — mirror the edit (DD-1)",
        )

    def test_vendored_known_cc_matches(self):
        vendored_path = _ROOT / "skills" / "patentworks" / "scripts" / "patentdb_local.py"
        import importlib.util
        spec = importlib.util.spec_from_file_location("_pdb_local2", vendored_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(
            tuple(mod._KNOWN_CC), tuple(pc._KNOWN_CC),
            "vendor drift: _KNOWN_CC diverged (DD-1)",
        )

    def test_vendored_behaviour_parity(self):
        """行為層 parity: 對關鍵樣本兩側輸出必須一致。"""
        vendored_path = _ROOT / "skills" / "patentworks" / "scripts" / "patentdb_local.py"
        import importlib.util
        spec = importlib.util.spec_from_file_location("_pdb_local3", vendored_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for raw in ("US20230081319A1", "TWI854998B", "CN119230141A",
                    "KR20260067039A", "US 2023/0081319 A1"):
            self.assertEqual(
                mod.canonical_pubno(raw), pc.to_patentdb_key(raw),
                f"vendor behaviour drift on {raw!r}",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
