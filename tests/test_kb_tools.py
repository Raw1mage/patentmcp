"""R16 domain-KB serving tools (plan mcp_r16-domain-kb) — TV-1..TV-5, TV-7, TV-8.

Unit-level: calls the patentmcp_kb_query / patentmcp_kb_get tools directly
against the real repo KB at .specbase/ragbase.sqlite, with PATENTS_KB_DB
patched per test. TV-6 (two-door consistency vs specbase gate.ts) is a live
check run by the orchestrator.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
from pathlib import Path

import pytest

import patent_mcp_server.patents as P

REPO_ROOT = Path(__file__).resolve().parents[1]
KB_DB = REPO_ROOT / ".specbase" / "ragbase.sqlite"
KNOWN_ID = "concept.gpss.api_specification"


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def kb_env(monkeypatch):
    monkeypatch.setenv("PATENTS_KB_DB", str(KB_DB))


# TV-1: FTS happy path — existing distilled object reachable in-band.
def test_tv1_fts_hits_known_object(kb_env):
    result = _run(P.patentmcp_kb_query("GPSS API"))
    assert result["success"] is True
    assert result["matchMode"] == "fts"
    ids = [h["id"] for h in result["hits"]]
    assert KNOWN_ID in ids
    assert result["total"] > 0
    hit = next(h for h in result["hits"] if h["id"] == KNOWN_ID)
    for field in ("id", "type", "title", "score", "confidence", "source_weight"):
        assert field in hit


# TV-2: short CJK tokens degrade to LIKE scan, self-described.
def test_tv2_short_tokens_like_scan(kb_env):
    result = _run(P.patentmcp_kb_query("檢索"))
    assert result["success"] is True
    assert result["matchMode"] == "like-scan"
    for h in result["hits"]:
        assert h["score"] == 0


# TV-2b: mixed tokens -> hybrid.
def test_tv2b_mixed_tokens_hybrid(kb_env):
    result = _run(P.patentmcp_kb_query("GPSS 圖"))
    assert result["success"] is True
    assert result["matchMode"] == "hybrid"


# TV-3: KB file missing → typed fail-fast envelope with remedy.
def test_tv3_kb_missing_unavailable(monkeypatch):
    monkeypatch.setenv("PATENTS_KB_DB", "/nonexistent/kb.sqlite")
    out = _run(P.patentmcp_kb_query("anything"))
    assert out["success"] is False
    assert out["error_code"] == "KB_UNAVAILABLE"
    assert "remedy" in out


# TV-3b: env unset → KB_UNAVAILABLE (no path guessing).
def test_tv3b_env_unset_unavailable(monkeypatch):
    monkeypatch.delenv("PATENTS_KB_DB", raising=False)
    out = _run(P.patentmcp_kb_query("anything"))
    assert out["success"] is False
    assert out["error_code"] == "KB_UNAVAILABLE"
    assert "remedy" in out


# TV-4: kb_get returns full body + provenance grading.
def test_tv4_kb_get_full_object(kb_env):
    result = _run(P.patentmcp_kb_get(KNOWN_ID))
    assert result["success"] is True
    for field in ("body_md", "confidence", "source_weight", "provenance"):
        assert field in result
    assert result["body_md"].strip()
    assert result["id"] == KNOWN_ID
    # KNOWN_ID has a distilled_from edge with source_weight 7
    assert result["source_weight"] == 7
    assert any(p["edge_type"] == "distilled_from" for p in result["provenance"])


# TV-4b: unknown id → KB_OBJECT_NOT_FOUND with consider affordance.
def test_tv4b_kb_get_unknown_id(kb_env):
    out = _run(P.patentmcp_kb_get("no.such.object"))
    assert out["success"] is False
    assert out["error_code"] == "KB_OBJECT_NOT_FOUND"
    assert "consider: patentmcp_kb_query" in out["message"]


# TV-5: read-only enforced — write attempt on the serving connection fails.
def test_tv5_query_only_blocks_writes(kb_env):
    conn = P._kb_connect()
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute(
                "INSERT INTO ragbase_objects (id, type, title) "
                "VALUES ('test.write.attempt', 'concept', 'x')")
    finally:
        conn.close()


# TV-7: empty query / empty id rejected.
def test_tv7_empty_query_rejected(kb_env):
    out = _run(P.patentmcp_kb_query("  "))
    assert out["success"] is False
    assert out["error_code"] == "KB_BAD_QUERY"


def test_tv7b_empty_id_rejected(kb_env):
    out = _run(P.patentmcp_kb_get("  "))
    assert out["success"] is False
    assert out["error_code"] == "KB_BAD_QUERY"


# TV-8: type filter + limit respected.
def test_tv8_type_filter_and_limit(kb_env):
    result = _run(P.patentmcp_kb_query("patent", type="concept", limit=3))
    assert result["success"] is True
    assert len(result["hits"]) <= 3
    for h in result["hits"]:
        assert h["type"] == "concept"


# Contract guard: read-only annotations declared on both tools.
def test_tools_readonly_annotations():
    import anyio

    async def _get():
        return {t.name: t for t in await P.mcp.list_tools()}

    tools = anyio.run(_get)
    for name in ("patentmcp_kb_query", "patentmcp_kb_get"):
        assert name in tools, f"{name} not registered"
        ann = tools[name].annotations
        assert ann is not None and ann.readOnlyHint is True
        assert ann.idempotentHint is True
        assert tools[name].description.startswith("READ-ONLY")
