"""Number-axis fail-loud + pub_number list tests (BR_20260718).

Covers: pub_number single/list -> GPSS PN condition, @PN suffix / outer-paren
cleaning, fail-loud on un-cleanable number-axis syntax, zero_hits grading, and
that a normal full-text keyword is never mis-detected. Pure-function level
(normalize_query + condition assembly), no live GPSS.
"""

import asyncio

import pytest

from patent_mcp_server import search_dispatcher as sd
from patent_mcp_server.search_dispatcher import (
    NumberAxisSyntaxError,
    _clean_number_axis,
    _looks_like_number_axis,
    normalize_query,
)


# ---- pub_number list -> PN condition (DD-1) -------------------------------

def _run(coro):
    return asyncio.run(coro)


async def _gpss_conditions(spec):
    """Capture the GPSSCondition list _run_gpss builds (no network)."""
    captured = {}

    class FakeGPSS:
        async def search(self, conditions, **kw):
            captured["conditions"] = conditions
            return {"success": True, "status": "success", "total": 0}

    await sd._run_gpss(spec, FakeGPSS())
    return captured["conditions"]


def _cond_map(conditions):
    return {c.field: c.value for c in conditions}


def test_pub_number_list_joined_to_pn():
    spec = normalize_query(pub_number=["CN117338286", "CN117338290"], num=5)
    conds = _cond_map(_run(_gpss_conditions(spec)))
    assert conds["PN"] == "CN117338286 or CN117338290"


def test_pub_number_single_backcompat():
    spec = normalize_query(pub_number="CN117338286", num=5)
    conds = _cond_map(_run(_gpss_conditions(spec)))
    assert conds["PN"] == "CN117338286"


# ---- @PN suffix / outer-paren cleaning (DD-2/DD-4) ------------------------

def test_clean_strips_pn_suffix_and_outer_parens():
    cleaned, audit = _clean_number_axis("(CN117338286 or CN117338290)@PN")
    assert cleaned == "CN117338286 or CN117338290"
    assert audit is not None
    assert "@PN" in audit["stripped"]
    assert "outer_parens" in audit["stripped"]


def test_normalize_cleans_number_axis_keyword():
    spec = normalize_query(
        keyword="(CN117338286 or CN117338290)@PN", keyword_field="PN")
    assert spec.keyword == "CN117338286 or CN117338290"
    assert spec.number_axis_cleaned is not None


def test_normalize_pn_field_bare_list_not_altered():
    # correct usage (no @PN, no parens) passes through untouched
    spec = normalize_query(
        keyword="CN117338286 or CN117338290", keyword_field="PN")
    assert spec.keyword == "CN117338286 or CN117338290"
    assert spec.number_axis_cleaned is None


# ---- fail-loud on un-cleanable syntax (DD-2) ------------------------------

def test_failloud_on_empty_after_clean():
    with pytest.raises(NumberAxisSyntaxError):
        normalize_query(keyword="()@PN", keyword_field="PN")


# ---- normal full-text keyword never mis-detected (DD-4) -------------------

def test_full_text_keyword_untouched():
    spec = normalize_query(keyword="wireless sensor network", keyword_field="TI/AB")
    assert spec.keyword == "wireless sensor network"
    assert spec.number_axis_cleaned is None


def test_looks_like_number_axis_discriminates():
    assert _looks_like_number_axis("CN117338286@PN") is True
    assert _looks_like_number_axis("CN117338286 or CN117338290") is True
    assert _looks_like_number_axis("wireless sensor network") is False
    assert _looks_like_number_axis("machine learning") is False
    assert _looks_like_number_axis(None) is False


# ---- zero_hits grading (DD-3) ---------------------------------------------

class _ZeroGPSS:
    """GPSS whose search reports a genuine zero-hit: the real zero branch is
    success:false + status:success + 'no record found' boilerplate."""
    async def search(self, conditions, **kw):
        return {"success": False, "status": "success",
                "message": "no record found", "total": 0}


def test_zero_hits_graded_for_number_axis():
    spec = normalize_query(pub_number=["ZZ999999"], num=5)
    records, total, note = _run(sd._run_gpss(spec, _ZeroGPSS()))
    assert records == []
    assert note == "likely_number_syntax_error"


def test_zero_hits_not_graded_for_full_text():
    spec = normalize_query(keyword="wireless sensor network",
                           keyword_field="TI/AB", num=5)
    records, total, note = _run(sd._run_gpss(spec, _ZeroGPSS()))
    assert records == []
    assert note is None
