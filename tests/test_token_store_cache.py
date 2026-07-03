"""Unit tests for TokenStore deliverable-cache extension (DD-5/DD-7, task group 4).

Covers:
  TV-1  provision idempotent per (owner, subject)
  TV-6  class-aware reaper (ephemeral idle vs deliverable-cache safety-net)
  TV-10 move traversal defence + cross-token forbidden by construction
  + dirty / export-snapshot cycle, credential set/verify, rehydrate compat.

Run: .venv/bin/python -m pytest tests/test_token_store_cache.py -v
"""
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _fresh_store(root, **kw):
    from patent_mcp_server._token_store import TokenStore
    return TokenStore(sessions_root=Path(root), **kw)


class TokenStoreCacheTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="tokstore_cache_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    # ── TV-1: provision idempotent ──────────────────────────────────
    def test_tv1_provision_idempotent(self):
        s = _fresh_store(self._tmp)
        a = s.provision("subjX", "ownerA")
        b = s.provision("subjX", "ownerA")
        self.assertEqual(a.token, b.token)
        self.assertEqual(a.token_class, "deliverable-cache")
        self.assertEqual(a.subject_id, "subjX")
        self.assertEqual(a.owner_identity, "ownerA")
        # different owner or subject → distinct token
        c = s.provision("subjX", "ownerB")
        d = s.provision("subjY", "ownerA")
        self.assertNotEqual(a.token, c.token)
        self.assertNotEqual(a.token, d.token)
        # find_by_subject resolves the live token
        self.assertEqual(s.find_by_subject("ownerA", "subjX").token, a.token)
        self.assertIsNone(s.find_by_subject("ownerA", "nope"))

    def test_provision_requires_both_ids(self):
        from patent_mcp_server._token_store import StagingError
        s = _fresh_store(self._tmp)
        with self.assertRaises(StagingError):
            s.provision("", "ownerA")
        with self.assertRaises(StagingError):
            s.provision("subj", "")

    # ── TV-6: class-aware reaper ────────────────────────────────────
    def test_tv6_ephemeral_idle_reaped(self):
        s = _fresh_store(self._tmp, ttl_seconds=100)
        e = s.put_bytes(b"hello", "a.txt")
        # force idle past ttl
        e.last_used_at -= 200
        reaped = s.reap_expired()
        self.assertEqual(reaped, 1)
        self.assertFalse((Path(self._tmp) / e.token).exists())

    def test_tv6_deliverable_cache_exempt_from_idle(self):
        s = _fresh_store(self._tmp, ttl_seconds=100)
        e = s.provision("subjZ", "ownerA")
        s.write_file(e.token, "draft.md", b"work")
        # idle well past the ephemeral ttl, but under the safety TTL
        e.last_used_at -= 500
        reaped = s.reap_expired()
        self.assertEqual(reaped, 0)
        self.assertTrue((Path(self._tmp) / e.token).exists())

    def test_tv6_deliverable_cache_safety_net_reaps(self):
        from patent_mcp_server import _token_store as ts
        s = _fresh_store(
            self._tmp, ttl_seconds=100,
        )
        # shrink safety envelope via monkeypatch on the module constants used
        s_safety, s_warn = ts.CACHE_SAFETY_TTL_SECONDS, ts.CACHE_SAFETY_WARN_SECONDS
        try:
            ts.CACHE_SAFETY_TTL_SECONDS = 300
            ts.CACHE_SAFETY_WARN_SECONDS = 100
            e = s.provision("subjW", "ownerA")
            s.write_file(e.token, "draft.md", b"dirty")
            # within warn window → WARNING but no reap
            e.last_used_at -= 250
            self.assertEqual(s.reap_expired(), 0)
            self.assertTrue((Path(self._tmp) / e.token).exists())
            # past full safety TTL → reap loudly
            e.last_used_at -= 200  # total 450 > 300
            self.assertEqual(s.reap_expired(), 1)
            self.assertFalse((Path(self._tmp) / e.token).exists())
        finally:
            ts.CACHE_SAFETY_TTL_SECONDS = s_safety
            ts.CACHE_SAFETY_WARN_SECONDS = s_warn

    def test_tv6_reactivation_resets_clock(self):
        s = _fresh_store(self._tmp, ttl_seconds=100)
        e = s.provision("subjR", "ownerA")
        e.last_used_at -= 500
        # any touch resets the clock
        s.resolve(e.token)
        self.assertEqual(s.reap_expired(), 0)

    # ── TV-10: move traversal + cross-token forbidden ───────────────
    def test_tv10_move_ok(self):
        s = _fresh_store(self._tmp)
        e = s.provision("subjM", "ownerA")
        s.write_file(e.token, "old/name.txt", b"payload")
        s.move(e.token, "old/name.txt", "new/name.txt")
        self.assertFalse((e.dir_path / "old" / "name.txt").exists())
        self.assertEqual((e.dir_path / "new" / "name.txt").read_bytes(), b"payload")

    def test_tv10_move_traversal_rejected(self):
        from patent_mcp_server._token_store import StagingError
        s = _fresh_store(self._tmp)
        e = s.provision("subjM2", "ownerA")
        s.write_file(e.token, "f.txt", b"x")
        with self.assertRaises(StagingError):
            s.move(e.token, "f.txt", "../escape.txt")
        with self.assertRaises(StagingError):
            s.move(e.token, "../../etc/passwd", "f2.txt")
        with self.assertRaises(StagingError):
            s.move(e.token, "f.txt", "/abs.txt")

    def test_tv10_move_missing_src(self):
        from patent_mcp_server._token_store import TokenNotFoundError
        s = _fresh_store(self._tmp)
        e = s.provision("subjM3", "ownerA")
        with self.assertRaises(TokenNotFoundError):
            s.move(e.token, "ghost.txt", "there.txt")

    def test_mkdir_traversal_rejected(self):
        from patent_mcp_server._token_store import StagingError
        s = _fresh_store(self._tmp)
        e = s.provision("subjMk", "ownerA")
        s.mkdir(e.token, "sub/dir")
        self.assertTrue((e.dir_path / "sub" / "dir").is_dir())
        with self.assertRaises(StagingError):
            s.mkdir(e.token, "../evil")

    # ── dirty / export snapshot cycle ───────────────────────────────
    def test_export_snapshot_dirty_cycle(self):
        s = _fresh_store(self._tmp)
        e = s.provision("subjE", "ownerA")
        s.write_file(e.token, "a.txt", b"one")
        s.write_file(e.token, "b.txt", b"two")
        # before any snapshot everything is dirty (added vs empty baseline)
        self.assertEqual(set(s.dirty_files(e.token)), {"a.txt", "b.txt"})
        # snapshot → clean
        snap = s.snapshot_exports(e.token)
        self.assertEqual(set(snap.keys()), {"a.txt", "b.txt"})
        self.assertIsNotNone(s.resolve(e.token).last_export_at)
        self.assertEqual(s.dirty_files(e.token), [])
        # modify → dirty for that file only
        s.write_file(e.token, "a.txt", b"one-modified")
        self.assertEqual(s.dirty_files(e.token), ["a.txt"])
        # add file → dirty
        s.snapshot_exports(e.token)
        s.write_file(e.token, "c.txt", b"three")
        self.assertEqual(s.dirty_files(e.token), ["c.txt"])
        # delete file → dirty
        s.snapshot_exports(e.token)
        (e.dir_path / "c.txt").unlink()
        self.assertEqual(s.dirty_files(e.token), ["c.txt"])

    # ── credential ──────────────────────────────────────────────────
    def test_credential_set_verify(self):
        s = _fresh_store(self._tmp)
        e = s.provision("subjC", "ownerA")
        self.assertFalse(s.verify_credential(e.token, "secret"))
        s.set_credential(e.token, "s3cr3t")
        self.assertTrue(s.verify_credential(e.token, "s3cr3t"))
        self.assertFalse(s.verify_credential(e.token, "wrong"))

    # ── rehydrate compatibility ─────────────────────────────────────
    def test_rehydrate_new_fields_persist(self):
        s = _fresh_store(self._tmp)
        e = s.provision("subjP", "ownerA")
        s.write_file(e.token, "d.txt", b"data")
        s.snapshot_exports(e.token)
        s.set_credential(e.token, "pw")
        # new store instance over same root re-reads sidecars
        s2 = _fresh_store(self._tmp)
        r = s2.resolve(e.token)
        self.assertEqual(r.token_class, "deliverable-cache")
        self.assertEqual(r.subject_id, "subjP")
        self.assertEqual(r.owner_identity, "ownerA")
        self.assertIsNotNone(r.last_export_at)
        self.assertIn("d.txt", r.export_snapshot)
        self.assertTrue(s2.verify_credential(e.token, "pw"))

    def test_rehydrate_old_sidecar_tolerated(self):
        import json
        from patent_mcp_server._token_store import _META_NAME
        # simulate an OLD sidecar lacking the new keys
        tok = "tok_OLDLEGACYSIDECAR000000000000000"
        d = Path(self._tmp) / tok
        d.mkdir(parents=True)
        (d / "x.txt").write_bytes(b"legacy")
        (d / _META_NAME).write_text(json.dumps({
            "token": tok, "filename": "x.txt",
            "sha256": "abc", "size_bytes": 6, "created_at": 1.0,
        }))
        s = _fresh_store(self._tmp)  # must not crash
        r = s.resolve(tok)
        self.assertEqual(r.token_class, "ephemeral")
        self.assertIsNone(r.subject_id)
        self.assertIsNone(r.last_export_at)
        self.assertEqual(r.export_snapshot, {})


if __name__ == "__main__":
    unittest.main()
