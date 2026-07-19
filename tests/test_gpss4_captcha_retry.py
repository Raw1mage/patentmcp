"""GPSS4 login CAPTCHA-retry resilience tests (patentmcp_gpss4-folder-tools 1.6).

Covers the _login_one_account CAPTCHA-retry loop (session.py:311-348, design.md
DD-3): an unknown glyph (a char never labeled in md5_table.json, e.g. the missing
'Z') makes the current slot unsolvable, so the loop must FETCH A FRESH SLOT and
retry — never submit a '?'-bearing code, never silently fall back. When every
attempt within max_captcha_retry stays unknown, it fail-fasts with
GPSS4LoginError. A slot that becomes solvable mid-retry logs in successfully.

No network: _fetch_login_page / _solve_captcha / _submit / _follow_refresh are
faked. This is the离线-provable half of task 1.6; filling the actual 'Z' glyph
sprite into md5_table.json is deferred (needs a live login that happens to draw
a Z — random + account-lockout risk).
"""

import asyncio

import pytest

from patent_mcp_server.gpss4.session import GPSS4LoginError, GPSS4Session


def _run(coro):
    return asyncio.run(coro)


class _FakeResp:
    def __init__(self, text: str, url: str = "https://tipo/landing"):
        self.text = text
        self.url = url
        self.status_code = 200


def _wire_captcha_retry(session, solve_sequence, *, authed_text="__AUTHED__"):
    """Fake the login primitives so the CAPTCHA-retry loop can be driven.

    solve_sequence: list of (code, unknown) tuples, one consumed per attempt
    (per fresh slot). unknown non-empty -> that slot is unsolvable. A tuple whose
    code is truthy AND unknown empty is a solvable slot that will authenticate.
    Records how many slots were fetched and how many submits happened.
    """
    session._captcha.ready = lambda: True
    stats = {"slots_fetched": 0, "submits": 0, "submitted_codes": []}
    seq = list(solve_sequence)

    async def _fetch_login_page():
        stats["slots_fetched"] += 1
        # (login_url, fields, gif_paths) — shapes irrelevant, primitives faked.
        return ("https://tipo/login", {"ID": "19"}, ["n0.gif"] * 5)

    async def _solve_captcha(login_url, gif_paths):
        # One entry per attempt; if exhausted, keep returning unknown.
        if seq:
            return seq.pop(0)
        return ("?????", ["deadbeef"])

    async def _submit(login_url, fields, code):
        stats["submits"] += 1
        stats["submitted_codes"].append(code)
        return _FakeResp(authed_text)

    async def _follow_refresh(resp, login_url):
        return resp

    session._fetch_login_page = _fetch_login_page
    session._solve_captcha = _solve_captcha
    session._submit = _submit
    session._follow_refresh = _follow_refresh
    # A solvable slot authenticates; the '?'-path never reaches here.
    session._page_is_authed = lambda text: text == authed_text
    return stats


# ---- 1.6: unknown glyph -> retry fresh slot (never submit '?') --------------

def test_unknown_glyph_retries_fresh_slot_never_submits():
    """An unknown glyph makes the slot unsolvable: the loop fetches a NEW slot
    and retries; it must NOT submit the '?'-bearing code. Here every attempt is
    unknown, so it exhausts max_captcha_retry and raises — with ZERO submits."""
    s = GPSS4Session(accounts=[("a", "p1")], max_captcha_retry=6)
    stats = _wire_captcha_retry(s, [("????Z", ["md5-of-Z"])] * 6)
    with pytest.raises(GPSS4LoginError) as ei:
        _run(s.login())
    # exhausted after N fresh slots, and NEVER submitted a '?'-code
    assert stats["slots_fetched"] == 6
    assert stats["submits"] == 0
    assert "unknown CAPTCHA glyph" in str(ei.value)


def test_retry_succeeds_when_a_later_slot_is_solvable():
    """First 2 slots draw the unlabeled glyph (unknown), the 3rd is fully
    solvable -> login succeeds on the 3rd slot. Proves the retry is effective,
    and only the solvable slot is ever submitted."""
    s = GPSS4Session(accounts=[("a", "p1")], max_captcha_retry=6)
    stats = _wire_captcha_retry(
        s,
        [("????Z", ["md5-of-Z"]),        # slot 1: unknown
         ("???Z?", ["md5-of-Z"]),        # slot 2: unknown
         ("12345", [])],                 # slot 3: solvable
    )
    res = _run(s.login())
    assert res["success"] is True
    assert res["attempt"] == 3
    assert res["code"] == "12345"
    assert stats["slots_fetched"] == 3
    # only the solvable slot was submitted; the two '?'-slots were skipped
    assert stats["submits"] == 1
    assert stats["submitted_codes"] == ["12345"]


def test_all_unknown_exhausts_retry_budget_fail_fast():
    """Every slot within the retry budget is unknown -> GPSS4LoginError after
    exactly max_captcha_retry fresh slots (fail-fast, no silent fallback)."""
    s = GPSS4Session(accounts=[("a", "p1")], max_captcha_retry=3)
    stats = _wire_captcha_retry(s, [])  # empty seq -> always unknown
    with pytest.raises(GPSS4LoginError) as ei:
        _run(s.login())
    assert stats["slots_fetched"] == 3
    assert stats["submits"] == 0
    assert "after 3 attempts" in str(ei.value)


def test_solvable_first_slot_no_retry_needed():
    """Baseline: a solvable first slot logs in on attempt 1, one slot, one
    submit — the retry machinery adds no overhead on the happy path."""
    s = GPSS4Session(accounts=[("a", "p1")], max_captcha_retry=6)
    stats = _wire_captcha_retry(s, [("ABCDE", [])])
    res = _run(s.login())
    assert res["success"] is True
    assert res["attempt"] == 1
    assert stats["slots_fetched"] == 1
    assert stats["submits"] == 1
