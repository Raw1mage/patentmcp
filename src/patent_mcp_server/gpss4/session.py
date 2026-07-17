"""
GPSS4 web-app session: auto-login (md5-lookup CAPTCHA) + TTS* cookie management.

Login sequence (reverse-engineered & verified 2026-07-11, design.md DD-2/3/4):

The whole chain must ride ONE session slot. GPSS4 carries session state in the
URL (an ID / SECU / RETURN-token minted per home-page load); re-fetching the
home page mints a NEW slot with a DIFFERENT CAPTCHA answer. So a single login
attempt fetches the home page ONCE and reuses that slot's ID/SECU through POST.

  1. GET  gpssbkm?@@<rand>                 -> home page (seeds TTS* cookies) +
                                              embedded login link (ID/SECU/RETURN)
  2. GET  <login link>                     -> login form; parse hidden ID/SECU/TPHC
                                              + the 5 glyph GIF urls (dir = 000<ID>)
  3. GET  accserverusr/000<ID>/n0..n4.gif  -> 5 glyph GIFs (SAME jar)
  4. md5-lookup each glyph -> 5-char code  (CaptchaTable; answer bound to slot)
  5. POST accserver  email / sys/00/passwd / sys/00/rand=<code> / ID / SECU / TPHC
     -> on success returns an HTML meta-refresh to gpsskm?ex=sso^<token>
  6. FOLLOW the meta-refresh chain -> TTSUID populated -> logged in

Session lives ~5400s (90 min). On expiry / redirect-to-login, re-login
automatically (approved behaviour, not a new silent fallback — design.md DD-4).

Multi-account login pool (patentmcp_gpss4-login-account-rotation): credentials
resolve to an ordered pool (GPSS4_USERNAME[_N] / GPSS4_PASSWORD[_N]); on login
failure the pool rotates to the next not-yet-failed account, and only when the
whole pool fails does login() raise. session-expiry re-login uses the current
valid account and does NOT rotate.
"""

from __future__ import annotations

import logging
import os
import random
import re
from typing import Dict, List, Optional, Tuple

import httpx

from patent_mcp_server.gpss4.ocr import CaptchaTable

logger = logging.getLogger(__name__)

BASE = "https://tiponet.tipo.gov.tw"
ENTRY = f"{BASE}/gpss4/gpsskmc/gpssbkm"
ACCSERVER = f"{BASE}/gpss4/gpsskmc/accserver"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# The home page (gpssbkm?@@rand, ~16KB) embeds the real login link carrying the
# per-session ID + SECU + a RETURN token. The login form (~7.6KB) then carries
# ID / SECU / TPHC as hidden inputs (unquoted attribute values, e.g.
# `<input type=hidden name=SECU value=2010841088>`). These per-session hidden
# values — NOT the TTSSECU cookie, NOT a hardcoded ID — are what the POST needs.
_LOGIN_LINK_RE = re.compile(
    r'href="(/gpss4/gpsskmc/accserver\?ID=\d+&SECU=-?\d+&PAGE=login&RETURN=[^"]*)"',
    re.I,
)
_HIDDEN_RE = re.compile(
    r'name=["\']?(ID|SECU|TPHC)["\']?\s+value=["\']?(-?\d+)', re.I
)
# The 5 glyph GIF urls embedded in the login form (dir = zero-padded session ID).
_GIF_RE = re.compile(r'(accserverusr/\d+/n\d\.gif\?\d+)', re.I)
# On login success, the POST body is an HTML meta-refresh to the SSO landing.
_REFRESH_RE = re.compile(r"URL='([^']+)'", re.I)


class GPSS4LoginError(RuntimeError):
    pass


def _load_accounts(explicit: Optional[List[Tuple[str, str]]]) -> List[Tuple[str, str]]:
    """Resolve the login account pool (DD-3).

    Priority: explicit constructor arg > numbered env vars. Account 1 is the
    un-suffixed GPSS4_USERNAME / GPSS4_PASSWORD (back-compat); accounts 2+ are
    GPSS4_USERNAME_2 / GPSS4_PASSWORD_2, _3, ... scanned CONSECUTIVELY until a
    number is missing. Only pairs where BOTH username and password are non-empty
    are admitted (credentials are paired, DD-3).
    """
    if explicit is not None:
        return [(u, p) for (u, p) in explicit if u and p]
    out: List[Tuple[str, str]] = []
    # Account 1: un-suffixed (legacy).
    u1 = os.getenv("GPSS4_USERNAME")
    p1 = os.getenv("GPSS4_PASSWORD")
    if u1 and p1:
        out.append((u1, p1))
    # Accounts 2+: consecutive numbered suffixes, stop at first gap.
    idx = 2
    while True:
        u = os.getenv(f"GPSS4_USERNAME_{idx}")
        p = os.getenv(f"GPSS4_PASSWORD_{idx}")
        if not (u and p):
            break
        out.append((u, p))
        idx += 1
    return out


class GPSS4Session:
    """Holds an authenticated httpx client (TTS* cookie jar) for GPSS4 web."""

    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        accounts: Optional[List[Tuple[str, str]]] = None,
        timeout: float = 40.0,
        max_captcha_retry: int = 6,
    ):
        # Back-compat: a single positional (username, password) seeds a
        # 1-account pool; otherwise resolve the numbered env pool (DD-3).
        explicit: Optional[List[Tuple[str, str]]] = None
        if accounts is not None:
            explicit = list(accounts)
        elif username and password:
            explicit = [(username, password)]
        self.accounts: List[Tuple[str, str]] = _load_accounts(explicit)
        self._cursor: int = 0
        self._failed_accounts: set = set()
        self.max_captcha_retry = max_captcha_retry
        self._captcha = CaptchaTable()
        self._client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": _UA},
        )
        self._logged_in = False
        self._authed = False
        # Every (url, html) hop the SSO meta-refresh chain walked during login.
        self._refresh_chain: list = []
        # The final SSO-landing URL that carries the authenticated slot token.
        # Populated by login(); a browser (playwright) MUST goto THIS url — a
        # bare gpssbkm?@@<n> mints a fresh anonymous slot (member nav absent).
        self.landing_url = ""

    @property
    def username(self) -> Optional[str]:
        """Current-cursor account username (back-compat: _submit reads this)."""
        if not self.accounts or self._cursor >= len(self.accounts):
            return None
        return self.accounts[self._cursor][0]

    @property
    def password(self) -> Optional[str]:
        """Current-cursor account password (back-compat: _submit reads this)."""
        if not self.accounts or self._cursor >= len(self.accounts):
            return None
        return self.accounts[self._cursor][1]

    def _advance_account(self) -> bool:
        """Mark the current account failed and move the cursor to the next
        not-yet-failed account. Returns True if such an account exists, False
        if the whole pool has now failed to log in (DD-4/DD-5)."""
        self._failed_accounts.add(self._cursor)
        for idx in range(len(self.accounts)):
            if idx not in self._failed_accounts:
                self._cursor = idx
                return True
        return False

    def configured(self) -> bool:
        return bool(self.accounts)

    # ---- low-level steps -------------------------------------------------

    async def _fetch_login_page(self):
        """Steps 1-2: load the home page ONCE, follow its embedded login link,
        and return (login_url, fields{ID,SECU,TPHC}, gif_paths[5]).

        Everything below must ride this ONE slot: ID / SECU come from the
        login-form hidden inputs (NOT the TTSSECU cookie, NOT a hardcoded ID),
        and the 5 glyph GIF paths carry the slot's zero-padded ID directory
        (design.md DD-2, verified 2026-07-11). Re-loading the home page mints a
        new slot with a different CAPTCHA answer, so callers must NOT re-fetch.
        """
        home = await self._client.get(f"{ENTRY}?@@{random.randint(1, 9_999_999)}")
        link_m = _LOGIN_LINK_RE.search(home.text)
        if not link_m:
            raise GPSS4LoginError("login link not found on home page")
        login_url = BASE + link_m.group(1)
        page = await self._client.get(login_url, headers={"Referer": str(home.url)})
        html = page.text
        fields: Dict[str, str] = {}
        for name, val in _HIDDEN_RE.findall(html):
            fields[name.upper()] = val
        if "ID" not in fields or "SECU" not in fields:
            raise GPSS4LoginError(
                f"login form missing hidden fields (got {list(fields)}, "
                f"page_len={len(html)})"
            )
        fields.setdefault("TPHC", "2")
        gif_paths = _GIF_RE.findall(html)
        if len(gif_paths) != 5:
            raise GPSS4LoginError(
                f"expected 5 CAPTCHA glyph urls, found {len(gif_paths)}"
            )
        return login_url, fields, gif_paths

    async def _solve_captcha(self, login_url: str, gif_paths: List[str]):
        """Steps 3-4: fetch the 5 glyph GIFs on the same slot, md5-lookup each.

        Returns (code, unknown_md5s). code has '?' for any unknown glyph.
        """
        glyphs: List[bytes] = []
        for g in gif_paths:
            r = await self._client.get(
                f"{BASE}/gpss4/{g}", headers={"Referer": login_url}
            )
            glyphs.append(r.content)
        return self._captcha.recognize(glyphs)

    async def _submit(self, login_url: str, fields: Dict[str, str], code: str):
        """Step 5: POST the login form with the slot's hidden fields."""
        data = {
            "email": self.username,
            "sys/00/passwd": self.password,
            "sys/00/rand": code,
            "ID": fields["ID"],
            "SECU": fields["SECU"],
            "TPHC": fields.get("TPHC", "2"),
            "_BTN_登入/Login^^^Si": "登入/Login",
        }
        return await self._client.post(
            ACCSERVER, data=data, headers={"Referer": login_url}
        )

    async def _follow_refresh(self, resp: httpx.Response, referer: str, depth: int = 0):
        """Step 6: follow the HTML meta-refresh chain (SSO landing) after a
        successful POST. httpx does not auto-follow HTML meta-refresh, so we
        walk it manually until TTSUID is populated or the chain ends.

        Record every hop (url, html) so callers can recover the member-frame
        page: the SSO landing chain is one-time (its ex=sso^ token is consumed
        on walk), so the member nav HTML must be captured HERE, not re-fetched.
        """
        self._refresh_chain.append((str(resp.url), resp.text))
        if depth > 4:
            return resp
        m = _REFRESH_RE.search(resp.text)
        if not m:
            return resp
        target = m.group(1)
        url = target if target.startswith("http") else BASE + target
        nxt = await self._client.get(url, headers={"Referer": referer})
        return await self._follow_refresh(nxt, url, depth + 1)

    def _is_authenticated(self) -> bool:
        """Login succeeded when the landing page shows logged-in markers.

        design.md DD-4 originally assumed a populated TTSUID cookie, but real
        testing (2026-07-11) showed TTSUID stays empty even when logged in — the
        session identity rides the URL SSO token, not that cookie. The reliable
        signal is the SSO landing page carrying the member-area markers.
        """
        return self._authed

    _LOGIN_MARKERS = ("登出", "logout", "專案", "資料夾")

    def _page_is_authed(self, html: str) -> bool:
        return sum(1 for m in self._LOGIN_MARKERS if m in html) >= 2

    # ---- public API ------------------------------------------------------

    async def _login_one_account(self) -> Dict[str, object]:
        """Run the full login sequence for the CURRENT-cursor account, with
        CAPTCHA-retry. Returns a success status dict, or raises GPSS4LoginError
        if this account cannot be logged in after max_captcha_retry attempts
        (DD-2). The rotation loop in login() decides whether to try another
        account.
        """
        last_err = ""
        for attempt in range(1, self.max_captcha_retry + 1):
            # One slot per attempt: home->login page (fields + gif urls), same jar.
            login_url, fields, gif_paths = await self._fetch_login_page()
            code, unknown = await self._solve_captcha(login_url, gif_paths)
            if unknown:
                # A glyph char we've never labeled -> this slot is unsolvable;
                # retry with a fresh slot (new glyphs). Not a silent fallback:
                # it's the CAPTCHA-retry the loop exists for (design.md DD-3).
                last_err = f"unknown CAPTCHA glyph(s) md5={unknown}"
                logger.info("gpss4 login attempt %d: %s", attempt, last_err)
                continue
            resp = await self._submit(login_url, fields, code)
            resp = await self._follow_refresh(resp, login_url)
            self._authed = self._page_is_authed(resp.text)
            if self._is_authenticated():
                self._logged_in = True
                # Preserve the authenticated SSO-landing URL so a browser can
                # goto it directly (its slot token is what carries the session).
                self.landing_url = str(resp.url)
                return {
                    "success": True,
                    "attempt": attempt,
                    "code": code,
                    "uid": self._client.cookies.get("TTSUID", ""),
                }
            captcha_err = "驗證碼錯誤" in resp.text
            last_err = (
                f"login rejected (code={code}, captcha_err={captcha_err}, "
                f"http={resp.status_code})"
            )
            logger.info("gpss4 login attempt %d: %s", attempt, last_err)

        raise GPSS4LoginError(
            f"login failed after {self.max_captcha_retry} attempts: {last_err}"
        )

    async def login(self) -> Dict[str, object]:
        """Run the login sequence, rotating through the account pool on failure.

        Tries the current-cursor account via _login_one_account(); if it fails
        (CAPTCHA exhausted / credentials rejected / HTTP error), marks it failed
        for this process, rotates to the next not-yet-failed account, and
        retries. When the whole pool has failed, raises GPSS4LoginError
        (DD-1..DD-5). session-expiry re-login uses the current valid account, it
        does NOT rotate (DD-6).
        """
        if not self.configured():
            raise GPSS4LoginError(
                "GPSS4_USERNAME / GPSS4_PASSWORD not set (env or .env)."
            )
        if not self._captcha.ready():
            raise GPSS4LoginError(
                "CAPTCHA md5 table missing (gpss4/captcha_data/md5_table.json)."
            )
        errors: List[str] = []
        while self._cursor < len(self.accounts):
            acct_user = self.username
            try:
                return await self._login_one_account()
            except GPSS4LoginError as e:
                errors.append(f"account #{self._cursor} ({acct_user}): {e}")
                logger.warning(
                    "gpss4 account #%d (%s) login failed, rotating to next",
                    self._cursor, acct_user,
                )
                if not self._advance_account():
                    break  # whole pool exhausted
        n = len(self.accounts)
        logger.error("gpss4 all %d accounts failed to login", n)
        raise GPSS4LoginError(
            f"login failed after trying {n} account(s): " + "; ".join(errors)
        )

    async def ensure_logged_in(self) -> None:
        if not self._logged_in or not self._is_authenticated():
            await self.login()

    async def get(self, url: str, **kw) -> httpx.Response:
        """Authenticated GET with auto re-login on redirect-to-login."""
        await self.ensure_logged_in()
        resp = await self._client.get(url, **kw)
        if "PAGE=login" in str(resp.url) or "accserver" in str(resp.url):
            # session expired -> re-login once, retry
            self._logged_in = False
            await self.login()
            resp = await self._client.get(url, **kw)
        return resp

    @property
    def client(self) -> httpx.AsyncClient:
        return self._client

    async def close(self) -> None:
        await self._client.aclose()
