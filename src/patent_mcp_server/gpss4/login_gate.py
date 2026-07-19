"""GPSS4 登入模式 in-memory login gate (BR_20260719 §4A).

.. deprecated:: patentmcp_gpss4-session-keepalive (2026-07-19)
    此 gate 的互斥語義（§4A 禁並發/禁雙登入 + DD-7 真進程校驗 + fail-fast-on-busy）
    已完全併入 ``gpss4.session_manager._SessionManager``（DD-3）：新模型把「in-use 期
    互斥」與「session 存活期 keep-alive」兩個生命週期解耦，login gate 的 per-call
    acquire/release 被 SessionManager 的 acquire(reuse-or-mint)/release(keep-alive)
    取代。所有 4 個登入模式進入點已改用 ``session_manager.shared_session``。
    本模組保留為 deprecated shim（避免破壞任何殘留 import），**新程式碼請勿再用**。


登入模式（web headless）**禁並發、禁雙登入**——這是 TIPO 帳號節流鎖定的血淚硬規則
（本 session 曾因 37min 內 5 次重啟、一度兩 loop + docker exec 探針三條 session 並存
把帳號打進鎖定）。互斥不能靠 AI 自律（最不可靠那環），必須是 process 層 code gate。

契約（design.md DD-5/DD-6/DD-7）:
- **process 內全局互斥**：module-level 單一 gate；任何觸發 web 登入的登入模式入口進場
  前必須 `acquire`。
- **拿不到即 fail-fast**：gate 已被持有 → 立即 raise `GPSS4LoginBusyError`（帶現持有者
  + 取得時間），**不排隊、不重試、不開第二 session**（§4A 天條）。
- **gate 與 OS 進程一致**（DD-7）：持有者記錄真進程 exe（readlink /proc/self/exe），
  release 校驗一致性，避免 gate 說空但實際殘留、或牌子卡住。
- **邊界**：本 gate 只管**登入模式**；GPSS REST API（官方金鑰、配額制、不碰登入面）
  不受此 gate 限制，可並行——不要誤把 REST 也鎖進來。

用法（context manager，release 保證在 finally）:

    from patent_mcp_server.gpss4.login_gate import login_gate

    async with login_gate("gpss4_resolve_appnos"):
        # ... 登入 + 查詢 ...
    # 離開 with 區塊自動 release（含例外路徑）
"""
from __future__ import annotations

import os
import time
from typing import Optional


class GPSS4LoginBusyError(RuntimeError):
    """登入模式 gate 已被別的登入工作持有 —— fail-fast，不排隊不重試（§4A 天條）。"""


class _LoginGate:
    """Process 內全局登入模式互斥閘（非 re-entrant，單線天條）。

    刻意不用 asyncio.Lock 的 await-blocking 語義：本 gate 的契約是「拿不到就立即
    fail-fast」而非「排隊等」，所以用一個純旗標 + 立即檢查，而非可 await 的鎖。
    登入爬蟲本就單線序列，無跨 event-loop 並發需求。
    """

    def __init__(self) -> None:
        self._holder: Optional[str] = None
        self._acquired_at: Optional[float] = None
        self._released_at: Optional[float] = None
        self._holder_exe: Optional[str] = None

    @staticmethod
    def _self_exe() -> str:
        """真進程 exe 路徑（DD-7 一致性校驗依據；非 grep cmdline 避免自匹配假影）。"""
        try:
            return os.readlink(f"/proc/{os.getpid()}/exe")
        except OSError:
            return f"pid:{os.getpid()}"

    def acquire(self, holder: str) -> None:
        """取得 gate。已被持有 → raise GPSS4LoginBusyError（不排隊不重試）。"""
        if self._holder is not None:
            held_for = (time.monotonic() - self._acquired_at) if self._acquired_at else 0.0
            raise GPSS4LoginBusyError(
                f"GPSS4 login gate BUSY: held by {self._holder!r} "
                f"since {held_for:.0f}s ago (exe={self._holder_exe}); "
                f"{holder!r} refused — 登入模式禁並發/禁雙登入 (§4A), "
                "不排隊不重試,等現有登入工作結束再重派"
            )
        self._holder = holder
        self._acquired_at = time.monotonic()
        self._holder_exe = self._self_exe()

    def release(self, holder: str) -> None:
        """釋放 gate。校驗持有者一致（DD-7）；不一致僅記警示不硬失敗（release 應永遠成功）。"""
        if self._holder is None:
            return
        # 一致性校驗：釋放者應為現持有者、且同一真進程。
        if self._holder != holder or self._holder_exe != self._self_exe():
            # 交叉不一致：仍釋放（避免牌子卡死），但這是 DD-7 要偵測的異常訊號。
            import logging
            logging.getLogger(__name__).warning(
                "GPSS4 login gate release mismatch: holder=%r releaser=%r "
                "holder_exe=%r self_exe=%r — releasing anyway",
                self._holder, holder, self._holder_exe, self._self_exe(),
            )
        self._holder = None
        self._acquired_at = None
        self._released_at = time.monotonic()
        self._holder_exe = None

    def status(self) -> dict:
        """gate 狀態（可觀測，DD-7）：現持有者 / 空閒 / 上次釋放時間。"""
        return {
            "busy": self._holder is not None,
            "holder": self._holder,
            "held_for_sec": (
                round(time.monotonic() - self._acquired_at, 1)
                if self._acquired_at else None
            ),
            "released_ago_sec": (
                round(time.monotonic() - self._released_at, 1)
                if self._released_at else None
            ),
        }


# module-level 單一 gate（process 內全局互斥）
_GATE = _LoginGate()


class login_gate:
    """Async context manager：進場 acquire、離場（含例外）release。

    async with login_gate("gpss4_resolve_appnos"):
        ...
    """

    def __init__(self, holder: str) -> None:
        self._holder = holder

    async def __aenter__(self) -> "_LoginGate":
        _GATE.acquire(self._holder)
        return _GATE

    async def __aexit__(self, exc_type, exc, tb) -> None:
        _GATE.release(self._holder)


def gate_status() -> dict:
    """查詢全局 gate 狀態（讓 orchestrator 派登入工作前先確認空閒）。"""
    return _GATE.status()
