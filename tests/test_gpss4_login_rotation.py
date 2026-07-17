"""GPSS4 login account-pool rotation tests (patentmcp_gpss4-login-account-rotation).

Covers the account-pool parse (numbered-suffix scan / gap-stop / paired-only /
single-account back-compat) and the login rotation state machine (main-account
failure rotates to the next, whole-pool failure fail-fasts, session re-login
does NOT rotate). No network: _login_one_account is faked.
"""

import asyncio

import pytest

from patent_mcp_server.gpss4.session import (
    GPSS4LoginError,
    GPSS4Session,
    _load_accounts,
)

GPSS4_ENV_KEYS = [
    "GPSS4_USERNAME", "GPSS4_PASSWORD",
    "GPSS4_USERNAME_2", "GPSS4_PASSWORD_2",
    "GPSS4_USERNAME_3", "GPSS4_PASSWORD_3",
]


@pytest.fixture(autouse=True)
def _clear_gpss4_env(monkeypatch):
    for k in GPSS4_ENV_KEYS:
        monkeypatch.delenv(k, raising=False)


def _run(coro):
    return asyncio.run(coro)


# ---- account-pool parse (DD-3) --------------------------------------------

def test_pool_numbered_scan(monkeypatch):
    """TV-1: account 1 (un-suffixed) + _2, consecutive scan."""
    monkeypatch.setenv("GPSS4_USERNAME", "a@x.com")
    monkeypatch.setenv("GPSS4_PASSWORD", "p1")
    monkeypatch.setenv("GPSS4_USERNAME_2", "b@y.com")
    monkeypatch.setenv("GPSS4_PASSWORD_2", "p2")
    assert _load_accounts(None) == [("a@x.com", "p1"), ("b@y.com", "p2")]


def test_pool_single_account_backcompat(monkeypatch):
    """TV-2: only the un-suffixed pair -> 1-account pool, as before."""
    monkeypatch.setenv("GPSS4_USERNAME", "a@x.com")
    monkeypatch.setenv("GPSS4_PASSWORD", "p1")
    assert _load_accounts(None) == [("a@x.com", "p1")]


def test_pool_incomplete_pair_dropped(monkeypatch):
    """TV-3: _2 has username but no password -> not admitted."""
    monkeypatch.setenv("GPSS4_USERNAME", "a@x.com")
    monkeypatch.setenv("GPSS4_PASSWORD", "p1")
    monkeypatch.setenv("GPSS4_USERNAME_2", "b@y.com")
    assert _load_accounts(None) == [("a@x.com", "p1")]


def test_pool_gap_stops_scan(monkeypatch):
    """A gap at _2 stops the scan even if _3 is present."""
    monkeypatch.setenv("GPSS4_USERNAME", "a@x.com")
    monkeypatch.setenv("GPSS4_PASSWORD", "p1")
    # _2 missing entirely; _3 present -> pool is [account1] only.
    monkeypatch.setenv("GPSS4_USERNAME_3", "c@z.com")
    monkeypatch.setenv("GPSS4_PASSWORD_3", "p3")
    assert _load_accounts(None) == [("a@x.com", "p1")]


def test_pool_explicit_overrides_env(monkeypatch):
    monkeypatch.setenv("GPSS4_USERNAME", "env@x.com")
    monkeypatch.setenv("GPSS4_PASSWORD", "envp")
    assert _load_accounts([("x@a.com", "p")]) == [("x@a.com", "p")]


def test_init_current_account_properties():
    s = GPSS4Session(accounts=[("a", "p1"), ("b", "p2")])
    assert s.username == "a" and s.password == "p1"
    assert s.configured() is True


# ---- rotation state machine (DD-1/DD-2/DD-4/DD-5/DD-6) ---------------------

def _fake_login(session, results):
    """Patch _login_one_account so it succeeds/fails per the current account.

    results: dict username -> "success" | "fail".
    """
    async def _impl():
        user = session.username
        if results.get(user) == "success":
            session._logged_in = True
            session._authed = True
            return {"success": True, "used_account": user}
        raise GPSS4LoginError(f"faked login fail for {user}")

    session._login_one_account = _impl
    # CAPTCHA readiness is checked before the rotation loop.
    session._captcha.ready = lambda: True


def test_main_fail_rotates_to_second():
    """TV-4: account1 fails, account2 succeeds -> success on #2."""
    s = GPSS4Session(accounts=[("a", "p1"), ("b", "p2")])
    _fake_login(s, {"a": "fail", "b": "success"})
    res = _run(s.login())
    assert res["success"] is True
    assert res["used_account"] == "b"
    assert 0 in s._failed_accounts
    assert s.username == "b"


def test_all_fail_raises_tried_n():
    """TV-5: whole pool fails -> GPSS4LoginError mentioning tried 2."""
    s = GPSS4Session(accounts=[("a", "p1"), ("b", "p2")])
    _fake_login(s, {"a": "fail", "b": "fail"})
    with pytest.raises(GPSS4LoginError) as ei:
        _run(s.login())
    assert "trying 2 account" in str(ei.value)


def test_relogin_uses_current_account_no_rotation():
    """TV-6: a successful login keeps the cursor; a session-expiry re-login
    on the SAME session re-runs _login_one_account with the current account,
    it does not jump to another account."""
    s = GPSS4Session(accounts=[("a", "p1"), ("b", "p2")])
    calls = []

    async def _impl():
        calls.append(s.username)
        s._logged_in = True
        s._authed = True
        return {"success": True, "used_account": s.username}

    s._login_one_account = _impl
    s._captcha.ready = lambda: True

    _run(s.login())          # first login -> account a
    s._logged_in = False     # simulate session expiry
    _run(s.login())          # re-login
    assert calls == ["a", "a"]   # current account reused, not rotated


def test_empty_pool_raises():
    s = GPSS4Session(accounts=[])
    s._captcha.ready = lambda: True
    with pytest.raises(GPSS4LoginError):
        _run(s.login())
