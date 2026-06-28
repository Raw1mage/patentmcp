"""Unit tests for patentdb_store — the patentdb structured bibliographic layer.

Run: .venv/bin/python -m pytest tests/test_patentdb_store.py -v
 or: .venv/bin/python tests/test_patentdb_store.py   (stdlib unittest fallback)
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


class PatentdbStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="patentdb_test_")
        os.environ["PATENTS_DB_ROOT"] = self._tmp
        # fresh import each test so DB path env is honoured
        import importlib
        from patent_mcp_server import patentdb_store
        importlib.reload(patentdb_store)
        self.S = patentdb_store

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)
        os.environ.pop("PATENTS_DB_ROOT", None)

    # --- DD-3: 稀疏 put（只 pubno + 一個欄位）---
    def test_sparse_put(self):
        r = self.S.put("US20230081319A1", fields={"title_en": "CONSTRUCTION ESCROW"})
        self.assertEqual(r["action"], "created")
        self.assertTrue(r["completeness"]["title"])
        self.assertFalse(r["completeness"]["claim1"])

    # --- DD-4: 漸進合併不覆寫既有非空值 ---
    def test_progressive_merge_no_clobber(self):
        self.S.put("US20230081319A1", fields={"title_en": "ORIGINAL TITLE"})
        # 同件不同格式 pubno + 補 claim1 + 試圖覆寫 title
        r2 = self.S.put("US 2023/0081319 A1",
                        fields={"claim1": "A system...", "title_en": "SHOULD NOT WIN"})
        self.assertEqual(r2["action"], "updated")
        self.assertIn("claim1", r2["merged_fields"])
        self.assertNotIn("title_en", r2["merged_fields"])  # 既有非空不被覆寫
        q = self.S.query(publication_number="US20230081319A1")
        self.assertEqual(q["patent"]["title_en"], "ORIGINAL TITLE")
        self.assertTrue(q["completeness"]["claim1"])

    # --- overwrite=True 才覆寫 ---
    def test_overwrite_flag(self):
        self.S.put("TWI854998B", fields={"title_orig": "OLD"})
        self.S.put("TWI854998B", fields={"title_orig": "NEW"}, overwrite=True)
        q = self.S.query(publication_number="TWI854998B")
        self.assertEqual(q["patent"]["title_orig"], "NEW")

    # --- pubno 正規化：不同格式同件 ---
    def test_pubno_normalization(self):
        self.assertEqual(self.S.canonical_pubno("US20230081319A1"),
                         self.S.canonical_pubno("US 2023/0081319 A1"))
        self.assertEqual(self.S.canonical_pubno("TWI854998B"), "TWI854998")

    # --- FTS5 ≥3 字 + 英文 ---
    def test_fts_english(self):
        self.S.put("US20230081319A1",
                   fields={"title_en": "CONSTRUCTION ESCROW MILESTONE", "abstract": "video bidding escrow"})
        r = self.S.query(fts="escrow")
        self.assertEqual(r["match_mode"], "fts5")
        self.assertGreaterEqual(r["count"], 1)

    # --- CJK 2 字詞走 LIKE fallback ---
    def test_cjk_short_like_fallback(self):
        self.S.put("CN120543023A",
                   fields={"title_orig": "户内装修数字化管理方法", "abstract": "监理 验收"})
        short = self.S.query(fts="装修")
        self.assertEqual(short["match_mode"], "like_short")
        self.assertGreaterEqual(short["count"], 1)
        long = self.S.query(fts="数字化")
        self.assertEqual(long["match_mode"], "fts5")
        self.assertGreaterEqual(long["count"], 1)

    # --- query pubno 未命中 ---
    def test_query_not_found(self):
        r = self.S.query(publication_number="US99999999A1")
        self.assertFalse(r["found"])

    # --- import_records：只書目，評分欄位被忽略 ---
    def test_import_records_biblio_only(self):
        records = [
            {"pubno": "CN120543023A", "title": "户内装修", "claim1": "步骤S1",
             "cpc": "G06Q50/08", "relevance": 5, "score": 5, "tech_gist": "不該入庫"},
            {"pubno": "", "title": "no pubno skip"},
        ]
        r = self.S.import_records(records)
        self.assertEqual(r["imported"], 1)
        self.assertEqual(r["skipped"], 1)
        # 確認評分欄不存在於 schema
        import sqlite3
        conn = sqlite3.connect(str(Path(self._tmp) / "patentdb.sqlite"))
        cols = [c[1] for c in conn.execute("PRAGMA table_info(patents)").fetchall()]
        for screening_col in ("relevance", "score", "tech_gist", "reason"):
            self.assertNotIn(screening_col, cols)
        conn.close()

    # --- completeness flags 反映實際內容 ---
    def test_completeness_flags(self):
        self.S.put("US20230081319A1", fields={"title_en": "T"})
        q = self.S.query(publication_number="US20230081319A1")
        c = q["completeness"]
        self.assertTrue(c["title"])
        self.assertFalse(c["abstract"])
        self.assertFalse(c["pdf_path"])

    # --- blob register（pdf 路徑 + sha256）---
    def test_blob_register(self):
        self.S.put("US20230081319A1",
                   blobs={"pdf": {"path": "US/20230081319/specification.pdf", "sha256": "abc"}},
                   acquisition_cost="high")
        q = self.S.query(publication_number="US20230081319A1")
        self.assertEqual(q["patent"]["pdf_path"], "US/20230081319/specification.pdf")
        self.assertEqual(q["patent"]["acquisition_cost"], "high")
        self.assertTrue(q["completeness"]["pdf_path"])

    # --- stats ---
    def test_stats(self):
        self.S.put("US20230081319A1", fields={"claim1": "x"})
        self.S.put("CN120543023A", fields={"title_orig": "y"})
        st = self.S.stats()
        self.assertEqual(st["total"], 2)
        self.assertEqual(st["with_claim1"], 1)
        self.assertIn("US", st["by_country"])


if __name__ == "__main__":
    unittest.main()
