"""GPSS4 session keep-alive SSOT tests (patentmcp_gpss4-session-keepalive).

Covers the cross-call session manager: reuse-or-mint, §4A concurrency fail-fast,
release keep-alive, idle/absolute TTL reaping, health-fail rebuild, explicit
close, finally-path release, and the 4-entry GPSS4_LOGIN_BUSY typed-error
contract. No network: GPSS4Session.ensure_logged_in and _healthy are faked, and
the monotonic clock is monkeypatched to advance TTL windows.

Maps to test-vectors.json TV-1..TV-10.
"""

import asyncio

import pytest

import patent_mcp_server.gpss4.session_manager as sm
from patent_mcp_server.gpss4.session_manager import (
    GPSS4LoginBusyError,
    _SessionManager,
)


def _run(coro):
    return asyncio.run(coro)


class _FakeSession:
    """Stand-in for GPSS4Session: counts logins, never hits the network."""

    def __init__(self, healthy=True):
        self.login_count = 0
        self.closed = False
        self._healthy_flag = healthy
        self._logged_in = False
        self._authed = False

    async def ensure_logged_in(self):
        # mint path calls this once per fresh session.
        if not self._logged_in:
            self.login_count += 1
            self._logged_in = True
            self._authed = True

    async def close(self):
        self.closed = True

    def _is_authenticated(self):
        return self._authed

    def _page_is_authed(self, html):
        return self._healthy_flag


@pytest.fixture
def mgr(monkeypatch):
    """A fresh _SessionManager whose mint/health are faked (no network).

    - GPSS4Session() -> a _FakeSession (per-mint fresh, login_count on it)
    - _healthy() -> returns the fake session's health flag directly (no GET)
    - monotonic clock is a mutable list so tests can advance it
    """
    minted = []

    def _fake_ctor(*a, **k):
        s = _FakeSession(healthy=_fake_ctor.next_healthy)
        minted.append(s)
        return s

    _fake_ctor.next_healthy = True
    monkeypatch.setattr(sm, "GPSS4Session", _fake_ctor)

    async def _fake_healthy(self, s):
        return s._healthy_flag

    monkeypatch.setattr(_SessionManager, "_healthy", _fake_healthy)

    clock = {"t": 1000.0}
    monkeypatch.setattr(sm.time, "monotonic", lambda: clock["t"])

    m = _SessionManager(idle_ttl_sec=600.0, absolute_ttl_sec=3600.0)
    m._minted_sessions = minted
    m._ctor = _fake_ctor
    m._clock = clock
    return m


# ---- TV-1: reuse without re-login ----------------------------------------

def test_tv1_reuse_no_relogin(mgr):
    s1 = _run(mgr.acquire("A"))
    mgr.release("A")
    s2 = _run(mgr.acquire("A"))
    mgr.release("A")
    assert s1 is s2                       # same session object
    assert mgr._login_count == 1          # logged in exactly once
    assert mgr._reuse_count == 1


# ---- TV-2: first acquire mints once --------------------------------------

def test_tv2_mint_once(mgr):
    s = _run(mgr.acquire("A"))
    assert s is not None
    assert mgr._login_count == 1
    st = mgr.status()
    assert st["live"] is True and st["busy"] is True


# ---- TV-3: concurrent acquire fail-fast (§4A) ----------------------------

def test_tv3_concurrent_fail_fast(mgr):
    _run(mgr.acquire("A"))               # A holds, not released
    with pytest.raises(GPSS4LoginBusyError) as ei:
        _run(mgr.acquire("B"))
    assert "BUSY" in str(ei.value)
    # live session count stays 1; A still holds.
    assert mgr.status()["holder"] == "A"
    assert mgr._login_count == 1


# ---- TV-4: release is keep-alive, not close ------------------------------

def test_tv4_release_keeps_alive(mgr):
    s = _run(mgr.acquire("A"))
    mgr.release("A")
    st = mgr.status()
    assert st["live"] is True
    assert st["busy"] is False
    assert s.closed is False


# ---- TV-5: idle TTL expiry -> rebuild on next acquire --------------------

def test_tv5_idle_ttl_rebuild(mgr):
    s1 = _run(mgr.acquire("A"))
    mgr.release("A")
    mgr._clock["t"] += 601.0             # past idle TTL (600s)
    s2 = _run(mgr.acquire("A"))
    assert s1.closed is True             # old closed
    assert s1 is not s2                  # rebuilt
    assert mgr._login_count == 2


# ---- TV-6: absolute TTL expiry -> forced rebuild (even if not idle) ------

def test_tv6_absolute_ttl_rebuild(mgr):
    s1 = _run(mgr.acquire("A"))
    mgr.release("A")
    # stay active (bump last_used) but cross absolute TTL.
    mgr._clock["t"] += 300.0
    _run(mgr.acquire("A"))               # reuse, refreshes last_used
    mgr.release("A")
    mgr._clock["t"] += 3400.0            # total age > 3600 absolute, idle < 600
    s2 = _run(mgr.acquire("A"))
    assert s1.closed is True
    assert s1 is not s2
    assert mgr._login_count == 2


# ---- TV-7: health-check fail -> close + mint -----------------------------

def test_tv7_health_fail_rebuild(mgr):
    s1 = _run(mgr.acquire("A"))
    mgr.release("A")
    s1._healthy_flag = False             # existing session goes unhealthy
    s2 = _run(mgr.acquire("A"))          # within TTL but unhealthy
    assert s1.closed is True
    assert s1 is not s2
    assert mgr._login_count == 2


# ---- TV-8: explicit close empties SSOT -----------------------------------

def test_tv8_explicit_close(mgr):
    s = _run(mgr.acquire("A"))
    mgr.release("A")
    res = _run(mgr.close())
    assert res["closed"] is True
    assert res["was_busy"] is False
    assert s.closed is True
    assert mgr.status()["live"] is False


def test_tv8b_close_while_busy_flags(mgr):
    _run(mgr.acquire("A"))               # still in-use
    res = _run(mgr.close())
    assert res["was_busy"] is True
    assert mgr.status()["live"] is False


# ---- TV-9: release in finally (exception path) ---------------------------

def test_tv9_release_on_exception(mgr):
    async def _work():
        async with sm_shared(mgr, "A") as s:
            raise ValueError("boom")

    with pytest.raises(ValueError):
        _run(_work())
    # released despite exception; session kept alive.
    st = mgr.status()
    assert st["busy"] is False
    assert st["live"] is True


# ---- release mismatch is warned, not fatal -------------------------------

def test_release_mismatch_still_releases(mgr):
    _run(mgr.acquire("A"))
    mgr.release("B")                     # wrong holder
    assert mgr.status()["busy"] is False # released anyway


# helper: a context-manager bound to a specific test manager instance --------

class sm_shared:
    def __init__(self, manager, holder):
        self._m = manager
        self._holder = holder

    async def __aenter__(self):
        return await self._m.acquire(self._holder)

    async def __aexit__(self, exc_type, exc, tb):
        self._m.release(self._holder)
