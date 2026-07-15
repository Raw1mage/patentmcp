"""observability log — patentmcp 的**統一**觀測記錄機制。

plan observability_tool-friction-log (DD-1..DD-5) + unified 擴充 (DD-6..DD-8)。

一個 store、一張表、一個 record_event API、一個查詢面。所有觀測事件
(工具 error、靜默磨擦、HTTP 存取)都是同一張 `events` 表的不同 category:

  category='friction', kind='exception' — 工具未捕捉例外(friction_tool wrapper 自動帶入)
  category='friction', kind='silent'    — logger.warning(...)+continue 型靜默磨擦(顯式埋點)
  category='access',   kind='http'      — 每個進來的 HTTP 請求(W3C 語義,ASGI middleware)

寫入 API:
  * record_event(category, kind, ...)   — 統一底層寫入(fail-open)。
  * record_friction(kind, ...)          — friction 薄包裝(向後相容,呼叫端不改)。
  * record_access(...)                  — HTTP 存取薄包裝(W3C 語義欄位)。
  * friction_tool(orig_tool)            — 中央 exception 攔截 decorator(DD-1)。

設計鐵律:
  * fail-open(DD-4)—— 記錄自身任何錯誤只 logger.warning 後吞掉,絕不 raise。
    觀測機制不得成為服務故障源。
  * 不改回傳契約 —— 只旁路記錄,工具/HTTP 對呼叫端行為完全不變。
  * 落點寄生 ./patentdb bind-mount(DD-3)—— 與 patentdb.sqlite 同目錄,
    rebuild 存活,不需新 volume。檔名 observability.sqlite。
  * 不存憑證/完整 payload(DD-5)—— args 只存短摘要,reason 截斷,URI query 剝除。

模組名保留 friction_log(既有 import 相容);語義已升級為 unified observability。
"""
from __future__ import annotations

import functools
import inspect
import json
import logging
import re as _re
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("patents_mcp.observability")

# ---------------------------------------------------------------------
# DB 落點 — 複用 patentdb_store 的 root 解析,寄生同一 ./patentdb bind-mount。
# ---------------------------------------------------------------------

_DB_FILENAME = "observability.sqlite"
_conn: Optional[sqlite3.Connection] = None
_init_failed = False  # 一旦 init 失敗即降級 no-op,不每次重試刷 stderr


def _db_path() -> Path:
    # 延遲 import 避免與 patentdb_store 的循環相依;它是純函式,安全。
    from patent_mcp_server.patentdb_store import _resolve_db_root

    root = _resolve_db_root()
    root.mkdir(parents=True, exist_ok=True)
    return root / _DB_FILENAME


# 統一事件表。共用欄位(ts/category/kind/tool/reason/detail) + friction 專屬
# (source/args_summary) + access 專屬(W3C 語義:method/uri/status/duration_ms/
# client_ip/user_agent/mcp_client)。單表 + category 索引 = 一個查詢面。
_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           REAL    NOT NULL,           -- epoch seconds (time.time())
    category     TEXT    NOT NULL,           -- 'friction' | 'access'
    kind         TEXT    NOT NULL,           -- friction: exception|silent ; access: http
    -- 共用
    tool         TEXT,                       -- 工具名(friction wrapper / access 解析 MCP tool)
    reason       TEXT,                       -- friction: 正規化理由 ; access: 選填
    detail       TEXT,                       -- 補充(截斷)
    -- friction 專屬
    source       TEXT,                       -- 磨擦來源(gpss/epo/ppubs/patentdb/...)
    args_summary TEXT,                       -- 關鍵參數短摘要(絕不含憑證/完整 payload)
    -- access 專屬(W3C Extended Log 語義)
    method       TEXT,                       -- cs-method (GET/POST/...)
    uri          TEXT,                       -- cs-uri-stem (query 已剝除)
    status       INTEGER,                    -- sc-status
    duration_ms  INTEGER,                    -- time-taken (ms)
    client_ip    TEXT,                       -- c-ip
    user_agent   TEXT,                       -- cs(User-Agent)
    mcp_client   TEXT                        -- x-mcp-client(從 UA / initialize 解析)
);
CREATE INDEX IF NOT EXISTS ix_events_ts       ON events(ts);
CREATE INDEX IF NOT EXISTS ix_events_category ON events(category);
CREATE INDEX IF NOT EXISTS ix_events_kind     ON events(kind);
CREATE INDEX IF NOT EXISTS ix_events_tool     ON events(tool);
CREATE INDEX IF NOT EXISTS ix_events_status   ON events(status);
"""


def _get_conn() -> Optional[sqlite3.Connection]:
    """Lazy-init 單一 connection(WAL、冪等 schema)。失敗即降級 no-op。"""
    global _conn, _init_failed
    if _init_failed:
        return None
    if _conn is not None:
        return _conn
    try:
        path = _db_path()
        conn = sqlite3.connect(str(path), check_same_thread=False, timeout=2.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        conn.commit()
        _conn = conn
        return _conn
    except Exception as e:  # noqa: BLE001 — fail-open(DD-4)
        _init_failed = True
        logger.warning("observability: store unavailable, degrading to no-op: %s", e)
        return None


# ---------------------------------------------------------------------
# 正規化 helpers(DD-5)。
# ---------------------------------------------------------------------

_HTTP_RE = _re.compile(r"\b([45]\d\d)\b")


def normalize_reason(exc_or_msg: Any) -> str:
    """exception/字串 → 'http_error:NNN' 或截斷字串(複用 search_dispatcher 模式)。"""
    if isinstance(exc_or_msg, BaseException):
        msg = str(exc_or_msg)
        cls = exc_or_msg.__class__.__name__
    else:
        msg = str(exc_or_msg)
        cls = ""
    m = _HTTP_RE.search(msg)
    if m:
        return f"http_error:{m.group(1)}"
    return (msg[:200] or cls) or "unknown"


# 憑證類參數鍵 — 絕不入 log(對齊 patentworks doctrine:憑證絕不寫進 log)。
_SECRET_KEYS = {
    "password", "passwd", "secret", "token", "api_key", "apikey", "key",
    "consumer_key", "consumer_secret", "user_code", "usercode", "credential",
    "authorization", "auth", "owner_identity",
}


def summarize_args(kwargs: Dict[str, Any], cap: int = 300) -> str:
    """關鍵參數短摘要(JSON)。剔除憑證鍵、長值截斷、避免完整 payload/PII。"""
    try:
        out: Dict[str, Any] = {}
        for k, v in kwargs.items():
            if k.lower() in _SECRET_KEYS:
                out[k] = "***"
                continue
            if isinstance(v, str):
                out[k] = v if len(v) <= 80 else v[:80] + "…"
            elif isinstance(v, (int, float, bool)) or v is None:
                out[k] = v
            elif isinstance(v, (list, tuple)):
                out[k] = f"<{type(v).__name__} len={len(v)}>"
            elif isinstance(v, dict):
                out[k] = f"<dict keys={len(v)}>"
            else:
                out[k] = f"<{type(v).__name__}>"
        s = json.dumps(out, ensure_ascii=False, default=str)
        return s if len(s) <= cap else s[:cap] + "…"
    except Exception:  # noqa: BLE001 — 摘要失敗不阻斷記錄
        return "<args-summary-failed>"


# ---------------------------------------------------------------------
# 統一底層寫入(DD-4/DD-6)。
# ---------------------------------------------------------------------

def record_event(
    category: str,
    kind: str,
    *,
    tool: Optional[str] = None,
    reason: Optional[str] = None,
    detail: Optional[str] = None,
    source: Optional[str] = None,
    args_summary: Optional[str] = None,
    method: Optional[str] = None,
    uri: Optional[str] = None,
    status: Optional[int] = None,
    duration_ms: Optional[int] = None,
    client_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    mcp_client: Optional[str] = None,
) -> None:
    """統一寫一筆觀測事件。fail-open:任何錯誤只 warn 後吞掉,絕不 raise。"""
    try:
        conn = _get_conn()
        if conn is None:
            return
        conn.execute(
            "INSERT INTO events "
            "(ts, category, kind, tool, reason, detail, source, args_summary, "
            " method, uri, status, duration_ms, client_ip, user_agent, mcp_client) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                time.time(), category, kind, tool,
                (reason[:300] if reason else None),
                (detail[:500] if detail else None),
                source, args_summary,
                method,
                (uri[:500] if uri else None),
                status, duration_ms, client_ip,
                (user_agent[:300] if user_agent else None),
                mcp_client,
            ),
        )
        conn.commit()
    except Exception as e:  # noqa: BLE001 — fail-open(DD-4),觀測不得成為故障源
        logger.warning("observability: record failed (swallowed): %s", e)


def record_friction(
    kind: str,
    *,
    tool: Optional[str] = None,
    source: Optional[str] = None,
    reason: Optional[str] = None,
    detail: Optional[str] = None,
    args_summary: Optional[str] = None,
) -> None:
    """friction 薄包裝(向後相容 — patents.py 埋點與 wrapper 呼叫不必改)。

    kind:
      'exception' — 工具未捕捉例外(friction_tool wrapper 自動帶入)。
      'silent'    — logger.warning(...)+continue 型靜默磨擦(顯式埋點)。
    """
    record_event(
        "friction", kind, tool=tool, source=source,
        reason=reason, detail=detail, args_summary=args_summary,
    )


def record_access(
    *,
    method: Optional[str],
    uri: Optional[str],
    status: Optional[int],
    duration_ms: Optional[int],
    client_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    mcp_client: Optional[str] = None,
    tool: Optional[str] = None,
) -> None:
    """HTTP 存取薄包裝(W3C Extended Log 語義欄位)。每個 HTTP 請求一筆。"""
    record_event(
        "access", "http",
        method=method, uri=uri, status=status, duration_ms=duration_ms,
        client_ip=client_ip, user_agent=user_agent, mcp_client=mcp_client,
        tool=tool,
    )


# ---------------------------------------------------------------------
# envelope-層磨擦偵測(DD-9,BR_20260715 §0)。
#
# 工具並非只用 raise 表達失敗 —— 大量磨擦是「正常 return 一個帶
# 失敗旗標的 dict」(success:false / error / error_code / *_empty)。
# 這些不拋 exception,exception 攜截層看不到(BR_20260715 實例:
# cuboai client 踩 5 磨擦但 log 報 0 friction)。本層在成功回傳路徑
# 旁路檢查回傳 dict,偵到失敗旗標就記一筆 kind='silent'。
# 錯誤契約不變 —— 只旁路記錄,不改回傳。
# ---------------------------------------------------------------------

# 視為「成功」的 error_code 白名單 —— R13 landing redirect 並非磨擦
# (它是正常的兩平面分流信號,呼叫端該走 landed 腳本)。
_OK_ERROR_CODES = {"TOOL_LANDED"}

# 帶這些旗標 = 需呼叫端補一步的静默磨擦(非硬失敗,但體驗不順)。
_ADVISORY_FLAG_KEYS = ("claim1_empty", "biblio_truncated", "scraping_skipped")


def detect_envelope_friction(result: Any) -> Optional[Dict[str, str]]:
    """偵測工具回傳 dict 是否帶「静默磨擦」旗標。

    回傳 None 表示沒磨擦(正常成功);回傳 {reason, detail} 表示偵到磨擦。
    純函式,絕不 拋錯(fail-open 上層負責包)。

    偵測規則(任一成立):
      1. success 顯式為 False。
      2. 帶 error / error_code 且非白名單(TOOL_LANDED)。
      3. 帶 advisory 旗標(claim1_empty 等)且為 truthy。
    """
    if not isinstance(result, dict):
        return None
    # 規則 1:顯式 success=False。
    if result.get("success") is False:
        code = result.get("error_code") or result.get("error") or "unknown"
        code = str(code)
        if code in _OK_ERROR_CODES:
            return None
        return {"reason": _reason_from_code(code),
                "detail": f"success=false: {code[:180]}"}
    # 規則 2:沒 success 旗但帶 error/error_code(部分工具不回 success)。
    if "success" not in result:
        code = result.get("error_code") or result.get("error")
        if code is not None and str(code) not in _OK_ERROR_CODES:
            return {"reason": _reason_from_code(str(code)),
                    "detail": f"error envelope: {str(code)[:180]}"}
    # 規則 3:advisory 旗標(即使 success=true 也算静默磨擦 —— 需補一步)。
    for k in _ADVISORY_FLAG_KEYS:
        if result.get(k):
            return {"reason": f"advisory:{k}",
                    "detail": f"envelope flag {k}=truthy (caller needs a follow-up)"}
    return None


def _reason_from_code(code: str) -> str:
    """error_code/error 字串 → 正規化 reason(優先 http_error:NNN)。"""
    m = _HTTP_RE.search(code)
    if m:
        return f"http_error:{m.group(1)}"
    # 簡短 error_code(如 SCRAPING_REQUIRED)直接當 reason;長錯訊截斷。
    token = code.strip().split(":", 1)[0].split(" ", 1)[0]
    if token and token.isupper() and len(token) <= 40:
        return f"envelope:{token}"
    return f"envelope:{code[:60]}"


# ---------------------------------------------------------------------
# 中央 exception 攜截 wrapper(DD-1)+ envelope 磨擦旁路(DD-9)。
# ---------------------------------------------------------------------

def friction_tool(orig_tool: Callable[..., Any]) -> Callable[..., Any]:
    """回傳一個語義同 mcp.tool(...) 的 decorator,但額外攔截被裝飾工具的未捕捉
    exception,記一筆 category='friction' kind='exception' 後原樣 re-raise。

    參數 orig_tool 必須是**原始的** mcp.tool bound method —— 呼叫端在
    monkeypatch 前先捕獲(否則此處會遞迴呼叫被覆蓋後的自己,無限遞迴)。

    關鍵約束(DD-1):以 functools.wraps 保留原函式 __name__/__doc__/__wrapped__
    與 signature,讓 FastMCP 對參數 schema 的內省完全不受影響。async / sync
    兩型都處理。
    """

    def decorator(*d_args: Any, **d_kwargs: Any) -> Callable[[Callable], Any]:
        def register(fn: Callable) -> Any:
            tool_name = getattr(fn, "__name__", "unknown")

            if inspect.iscoroutinefunction(fn):
                @functools.wraps(fn)
                async def awrapper(*args: Any, **kwargs: Any):
                    try:
                        result = await fn(*args, **kwargs)
                    except Exception as exc:  # noqa: BLE001
                        record_friction(
                            "exception",
                            tool=tool_name,
                            reason=normalize_reason(exc),
                            detail=f"{exc.__class__.__name__}: {exc}",
                            args_summary=summarize_args(kwargs),
                        )
                        raise
                    _record_envelope_friction(tool_name, result, kwargs)
                    return result
                wrapped = awrapper
            else:
                @functools.wraps(fn)
                def swrapper(*args: Any, **kwargs: Any):
                    try:
                        result = fn(*args, **kwargs)
                    except Exception as exc:  # noqa: BLE001
                        record_friction(
                            "exception",
                            tool=tool_name,
                            reason=normalize_reason(exc),
                            detail=f"{exc.__class__.__name__}: {exc}",
                            args_summary=summarize_args(kwargs),
                        )
                        raise
                    _record_envelope_friction(tool_name, result, kwargs)
                    return result
                wrapped = swrapper

            # 交給**原始** mcp.tool() 完成註冊(schema 內省作用在 wrapped,
            # 但 functools.wraps 已把 signature/annotations 透傳)。
            return orig_tool(*d_args, **d_kwargs)(wrapped)

        return register

    return decorator


def _record_envelope_friction(tool_name: str, result: Any,
                              kwargs: Dict[str, Any]) -> None:
    """在工具成功回傳路徑旁路偵測 envelope-層磨擦並記 kind='silent'。

    fail-open:偵測/記錄自身任何錯誤只吐掉,絕不影響工具回傳。
    """
    try:
        friction = detect_envelope_friction(result)
        if friction is None:
            return
        record_friction(
            "silent",
            tool=tool_name,
            reason=friction["reason"],
            detail=friction["detail"],
            args_summary=summarize_args(kwargs),
        )
    except Exception as e:  # noqa: BLE001 — fail-open(DD-4)
        logger.warning("observability: envelope-friction detect failed (swallowed): %s", e)
