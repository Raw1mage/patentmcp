"""GPSS4 登入模式跨呼叫 session SSOT (patentmcp_gpss4-session-keepalive).

痛點：GPSS4 登入模式每個 MCP 呼叫各開/關一個 GPSS4Session、跨呼叫重登，燒登入額度
（TIPO 帳號對登入頻率節流鎖定，§4A 天條起源）。session 本身實測活 ~90min，壽命非
瓶頸——缺的是**跨呼叫復用同一 authed session 的 process 內 SSOT**。

本模組是那個 SSOT：process 內 module-level singleton，治理**至多一個** live authed
GPSS4Session，跨 MCP 呼叫復用。

契約（design.md DD-1..DD-7）:
- **DD-1 SSOT**：module-level 單一 SessionManager，所有登入模式進入點經它借還。
- **DD-2 acquire = reuse-or-mint + 復用前健康檢查**：有 live+健康+未逾 TTL → 復用不重登；
  否則 close 舊的、mint 新 session 登入一次。
- **DD-3 §4A 互斥（吸收 login_gate）**：同時至多一個 in-use holder；並發 acquire →
  fail-fast GPSS4LoginBusyError，不排隊/不重試/不開第二 session。live session 恆為 0 或 1。
  持有者記真進程 exe（readlink /proc/self/exe，承接 login_gate DD-7）。
- **DD-4 release = keep-alive**：release 只標 idle + 更新 last-used，**不 close**。真 close
  僅由顯式 close() 或 reaper 觸發（雙保險）。
- **DD-5 TTL<90min**：idle TTL（閒置回收）+ absolute TTL（自 mint 起強制回收，< ~90min
  slot 死線）。lazy-on-acquire 檢查為主。
- **DD-6 無 fallback**：session 失效（健康檢查失敗 / redirect-to-login / TTL 逾時）→
  乾淨重建或 fail-fast，絕不靜默續用可能失效的 session。
- **DD-7 邊界**：只治理登入模式共享 session；GPSS REST（官方金鑰、配額制）不入本 SSOT。

兩個生命週期解耦（本模組核心）：
- **in-use 期**（一次呼叫，仍 §4A 互斥 fail-fast）：acquire → release 之間。
- **session 存活期**（跨呼叫 keep-alive）：mint → reap 之間，橫跨多次 in-use。

用法（context manager，release 保證在 finally）:

    from patent_mcp_server.gpss4.session_manager import shared_session

    async with shared_session("gpss4_resolve_appnos") as s:
        await s.ensure_logged_in()   # 復用時已登入，no-op；mint 時登入一次
        # ... 用 s 跑查詢 ...
    # 離開 with 自動 release（keep-alive，不 close；含例外路徑）
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional

from patent_mcp_server.gpss4.session import GPSS4Session

logger = logging.getLogger(__name__)


class GPSS4LoginBusyError(RuntimeError):
    """登入模式共享 session 已被別的登入工作持用 —— fail-fast，不排隊不重試（§4A 天條）。"""


# 預設 TTL（DD-5，保守 < TIPO 實測 ~90min slot 死線）。可經環境變數覆寫。
_DEFAULT_IDLE_TTL_SEC = float(os.getenv("GPSS4_SESSION_IDLE_TTL_SEC", "600"))       # 10 min
_DEFAULT_ABSOLUTE_TTL_SEC = float(os.getenv("GPSS4_SESSION_ABSOLUTE_TTL_SEC", "3600"))  # 60 min


class _SessionManager:
    """Process 內單一共享 GPSS4 登入 session 的 SSOT（DD-1）。

    非 re-entrant，單線天條：同時至多一個 in-use holder（§4A，DD-3），且 live session
    恆為 0 或 1（禁雙登入不變式）。acquire 為同步臨界區（純旗標即時檢查，非 await-blocking
    ——登入爬蟲本單線序列，無跨 event-loop 並發需求，承接 login_gate 設計）。
    """

    def __init__(
        self,
        idle_ttl_sec: float = _DEFAULT_IDLE_TTL_SEC,
        absolute_ttl_sec: float = _DEFAULT_ABSOLUTE_TTL_SEC,
    ) -> None:
        self._session: Optional[GPSS4Session] = None
        self._in_use_holder: Optional[str] = None
        self._holder_exe: Optional[str] = None
        self._minted_at: Optional[float] = None
        self._last_used_at: Optional[float] = None
        self.idle_ttl_sec = idle_ttl_sec
        self.absolute_ttl_sec = absolute_ttl_sec
        # 觀測用累計（observability.md）。
        self._login_count = 0
        self._reuse_count = 0
        self._busy_refused_count = 0

    @staticmethod
    def _self_exe() -> str:
        """真進程 exe 路徑（DD-3/DD-7 一致性校驗依據；非 grep cmdline 避免自匹配假影）。"""
        try:
            return os.readlink(f"/proc/{os.getpid()}/exe")
        except OSError:
            return f"pid:{os.getpid()}"

    # ---- TTL / health 判定 ------------------------------------------------

    def _absolute_expired(self, now: float) -> bool:
        return (
            self._minted_at is not None
            and (now - self._minted_at) >= self.absolute_ttl_sec
        )

    def _idle_expired(self, now: float) -> bool:
        return (
            self._last_used_at is not None
            and (now - self._last_used_at) >= self.idle_ttl_sec
        )

    async def _healthy(self, s: GPSS4Session) -> bool:
        """復用前輕量健康檢查（DD-2/DD-6）：確認 authed session 仍可達 member 面。

        探測用 session.get 打 KM 首頁（gpssbkm）——`session.get` 本身帶 redirect-to-login
        偵測：若 slot 已過期，它會被踢回 PAGE=login，get 自動重登一次並重試。健康信號用
        **最終回應 URL 是否被踢回登入頁**（resp.url 含 PAGE=login/accserver = 連重登都失敗
        = 真不健康），而非會員標記計數——KM 首頁是檢索框架頁、本就不含 登出/專案/資料夾
        會員標記，用 _page_is_authed 計數會把健康 session 恆判不健康（本 bug 根因，
        2026-07-19 live 坐實：health_fail→mint→login_count 每呼叫 +1，keep-alive 失效）。
        任何例外 → 不健康（無 fallback：不健康即重建）。
        """
        try:
            if not (s._logged_in and s._is_authenticated()):
                return False
            from patent_mcp_server.gpss4.session import ENTRY
            import random as _random
            resp = await s.get(f"{ENTRY}?@@{_random.randint(1, 9_999_999)}")
            # session.get 遇 redirect-to-login 已自動重登一次；此處只需確認最終沒被踢回
            # 登入頁（重登也失敗才會殘留 PAGE=login/accserver）。
            final_url = str(resp.url)
            if "PAGE=login" in final_url or "accserver" in final_url:
                return False
            return resp.status_code == 200
        except Exception as e:  # noqa: BLE001
            logger.info("gpss4 session health check failed: %s", e)
            return False

    async def _close_session(self, reason: str) -> None:
        """乾淨關閉並清出 SSOT（reap / 重建前）。"""
        if self._session is not None:
            try:
                await self._session.close()
            except Exception as e:  # noqa: BLE001
                logger.warning("gpss4 session close error (%s): %s", reason, e)
            logger.info("gpss4 session reap: reason=%s", reason)
        self._session = None
        self._minted_at = None
        self._last_used_at = None

    # ---- acquire / release (核心) ----------------------------------------

    async def acquire(self, holder: str) -> GPSS4Session:
        """借用共享 session（reuse-or-mint，DD-2）。

        - 已有 in-use holder → fail-fast GPSS4LoginBusyError（§4A，DD-3）。
        - live + 未逾 TTL + 健康 → 復用（不重登）。
        - 無 / 逾 TTL / 不健康 → close 舊的、mint 新 session 登入一次（DD-6 無 fallback）。
        """
        # §4A 互斥：拿不到即立即 fail-fast，不排隊不重試（DD-3）。
        if self._in_use_holder is not None:
            self._busy_refused_count += 1
            held_for = (time.monotonic() - self._last_used_at) if self._last_used_at else 0.0
            raise GPSS4LoginBusyError(
                f"GPSS4 login session BUSY: held by {self._in_use_holder!r} "
                f"since {held_for:.0f}s ago (exe={self._holder_exe}); "
                f"{holder!r} refused — 登入模式禁並發/禁雙登入 (§4A), "
                "不排隊不重試,等現有登入工作結束再重派"
            )

        now = time.monotonic()
        # TTL 檢查（DD-5，lazy-on-acquire）：逾期先清掉舊 session。
        if self._session is not None:
            if self._absolute_expired(now):
                await self._close_session("absolute_ttl")
            elif self._idle_expired(now):
                await self._close_session("idle_ttl")

        # 健康檢查（DD-2/DD-6）：復用前確認仍可達；不健康即重建。
        if self._session is not None:
            if await self._healthy(self._session):
                self._reuse_count += 1
                logger.info("gpss4 session reuse (holder=%s, age=%.0fs)",
                            holder, now - (self._minted_at or now))
            else:
                await self._close_session("health_fail")

        # mint（DD-2）：無 live session → 建新 + 登入一次。
        if self._session is None:
            s = GPSS4Session()
            await s.ensure_logged_in()
            self._session = s
            self._minted_at = time.monotonic()
            self._login_count += 1
            logger.info("gpss4 session mint (holder=%s, login_count=%d)",
                        holder, self._login_count)

        # 標記 in-use（§4A holder + DD-7 真進程 exe）。
        self._in_use_holder = holder
        self._holder_exe = self._self_exe()
        self._last_used_at = time.monotonic()
        return self._session

    def release(self, holder: str) -> None:
        """歸還共享 session（keep-alive，DD-4）：清 in-use holder，**不 close**。

        校驗持有者一致（DD-3/DD-7）；不一致僅記警示不硬失敗（release 應永遠成功，
        承接 login_gate release 契約）。session 留在 SSOT 供下次復用。
        """
        if self._in_use_holder is None:
            return
        if self._in_use_holder != holder or self._holder_exe != self._self_exe():
            logger.warning(
                "gpss4 session release mismatch: holder=%r releaser=%r "
                "holder_exe=%r self_exe=%r — releasing anyway",
                self._in_use_holder, holder, self._holder_exe, self._self_exe(),
            )
        self._in_use_holder = None
        self._holder_exe = None
        self._last_used_at = time.monotonic()  # keep-alive：idle 計時從歸還起算

    # ---- 顯式回收 / 可觀測 ------------------------------------------------

    async def close(self) -> dict:
        """顯式關閉共享 session（DD-4 雙保險之一）。回 {closed, was_busy}。"""
        was_busy = self._in_use_holder is not None
        had_session = self._session is not None
        if was_busy:
            logger.warning(
                "gpss4 session explicit close while in-use by %r — closing anyway",
                self._in_use_holder,
            )
        await self._close_session("explicit_close")
        self._in_use_holder = None
        self._holder_exe = None
        return {"closed": had_session, "was_busy": was_busy}

    def status(self) -> dict:
        """共享 session 狀態（可觀測，observability.md）。"""
        now = time.monotonic()
        live = self._session is not None
        age = (now - self._minted_at) if (live and self._minted_at) else None
        idle = (now - self._last_used_at) if (live and self._last_used_at) else None
        expires_in = (
            round(self.absolute_ttl_sec - age, 1)
            if age is not None else None
        )
        return {
            "live": live,
            "busy": self._in_use_holder is not None,
            "holder": self._in_use_holder,
            "age_sec": round(age, 1) if age is not None else None,
            "idle_sec": round(idle, 1) if idle is not None else None,
            "expires_in_sec": expires_in,
            "login_count": self._login_count,
            "reuse_count": self._reuse_count,
            "busy_refused_count": self._busy_refused_count,
            "idle_ttl_sec": self.idle_ttl_sec,
            "absolute_ttl_sec": self.absolute_ttl_sec,
        }


# module-level 單一 SSOT（process 內全局，DD-1）
_MANAGER = _SessionManager()


class shared_session:
    """Async context manager：進場 acquire（reuse-or-mint）、離場（含例外）release（keep-alive）。

        async with shared_session("gpss4_resolve_appnos") as s:
            await s.ensure_logged_in()
            ...
    """

    def __init__(self, holder: str) -> None:
        self._holder = holder

    async def __aenter__(self) -> GPSS4Session:
        return await _MANAGER.acquire(self._holder)

    async def __aexit__(self, exc_type, exc, tb) -> None:
        _MANAGER.release(self._holder)


async def close_shared_session() -> dict:
    """顯式關閉全局共享 session（gpss4_session_close tool 用）。"""
    return await _MANAGER.close()


def shared_session_status() -> dict:
    """查全局共享 session 狀態（gpss4_session_status tool 用）。"""
    return _MANAGER.status()


def _reset_for_test() -> None:
    """測試用：重置 module-level manager（不 close，僅清狀態旗標）。"""
    global _MANAGER
    _MANAGER = _SessionManager()
