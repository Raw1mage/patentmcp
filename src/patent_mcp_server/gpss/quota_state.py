"""GPSS time-window quota-exhausted state — cross-process sqlite sidecar.

BR_20260718 (supersedes owning plan DD-3 + Non-Goals). The old rotation design
latched an exhausted account in a **process-local** in-memory set keyed by cursor
index, with no time dimension. Two failures in a long-lived MCP-server process:

1. Cross-window waste: GPSS quota resets per time-window (weekday 08-18 narrow
   10,000 / off-hours + weekend wide 30,000). An account exhausted in one window
   stayed skipped for the whole process lifetime even after 18:00 flips the
   window and refills the quota — because the resident process never restarts.
2. Parallel stampede (DD-97): `gpss_client` is a module singleton; a
   process-local set is invisible to sibling subagent processes, so each starts
   at cursor #0 and burns both accounts independently.

This module fixes both with ONE mechanism: exhausted records are keyed by
`(account, window_key)` and persisted in a sqlite sidecar under `patentdb/`
(the shared rw bind-mount), so:

- **Implicit revival**: crossing a window boundary changes `window_key`, so the
  old record no longer matches the current window — the account becomes usable
  again with no explicit clear. Over-revival self-heals: a truly still-exhausted
  account re-hits "Over download quantity" on the next call and is re-marked
  under the new window_key.
- **Cross-process sharing**: parallel processes read/write the same sidecar, so
  one process marking an account exhausted is immediately visible to the others.

Design (owning plan DD-7 / DD-8):
- schema `(account TEXT, window_key TEXT, exhausted_at INT, PRIMARY KEY(account, window_key))`
- landing reuses `patentdb_store._resolve_db_root()` (patentdb_store does NOT
  import gpss, so this reverse import is safe from cycles).
- sqlite existence == in-memory cache; a read failure never blocks search
  (detection stays reactive — a still-exhausted account re-hits the quota
  signal and is re-marked).
"""
from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# GPSS quota resets on Taiwan local-time boundaries (08:00 / 18:00 on weekdays;
# off-hours + weekend are one wide window). We quantise "now" to a stable string
# key per window so an account marked exhausted in one window is automatically
# considered live again once the wall clock crosses into the next window.
_TAIPEI = timezone(timedelta(hours=8))

_SIDECAR_FILENAME = "gpss_quota_state.sqlite"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS gpss_quota_exhausted (
  account      TEXT NOT NULL,
  window_key   TEXT NOT NULL,
  exhausted_at INTEGER NOT NULL,
  PRIMARY KEY (account, window_key)
);
"""


def window_key(now: Optional[datetime] = None) -> str:
    """Quantise a moment to GPSS's quota-reset window (owning plan DD-7).

    GPSS windows (Taiwan local time):
      - weekday 08:00-18:00  -> the NARROW window (10,000 cap)
      - weekday 18:00-08:00 (overnight) + all weekend -> the WIDE window (30,000)

    The key must be:
      - STABLE within one window (same key for every call in that window), and
      - DISTINCT across windows (so crossing a boundary changes the key and
        implicitly revives an exhausted account).

    Encoding: `<YYYY-MM-DD>:<slot>` where slot is:
      - "narrow" for a weekday daytime moment (date = that calendar day), or
      - "wide:<anchor-date>" for an off-hours/weekend moment, where anchor-date
        is the calendar date of the wide window's START (so an overnight window
        spanning two dates shares one key, and does not fragment at midnight).

    A weekday 00:00-08:00 pre-dawn slice belongs to the PREVIOUS evening's wide
    window; its anchor is the previous calendar day.
    """
    if now is None:
        now = datetime.now(_TAIPEI)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=_TAIPEI)
    else:
        now = now.astimezone(_TAIPEI)

    weekday = now.weekday()  # Mon=0 .. Sun=6
    is_weekend = weekday >= 5  # Sat/Sun
    hour = now.hour

    if not is_weekend and 8 <= hour < 18:
        # Weekday daytime narrow window, one per calendar day.
        return f"{now.date().isoformat()}:narrow"

    # Otherwise a wide window (weekday overnight, or weekend). Anchor to the
    # calendar date on which this wide window STARTED so an overnight span does
    # not fracture at midnight.
    if is_weekend:
        # Walk back to the wide window's start: the most recent weekday 18:00
        # (Friday) OR the current day's 00:00 boundary is not needed — the whole
        # weekend from Fri 18:00 to Mon 08:00 is one wide window. Anchor to that
        # Friday's date.
        anchor = now
        # Step back to Friday.
        while anchor.weekday() != 4:  # Fri=4
            anchor = anchor - timedelta(days=1)
        return f"{anchor.date().isoformat()}:wide"

    # Weekday, but off-hours (hour < 8 or hour >= 18).
    if hour < 8:
        # Pre-dawn belongs to the previous day's evening wide window.
        anchor = now - timedelta(days=1)
        # If the previous day was Sunday/Saturday the weekend branch above would
        # have caught it; a weekday pre-dawn's previous day is a weekday or Fri.
        return f"{anchor.date().isoformat()}:wide"
    # hour >= 18: evening wide window starts today.
    return f"{now.date().isoformat()}:wide"


class QuotaStateStore:
    """Cross-process store of exhausted (account, window_key) records.

    Backed by a sqlite sidecar under patentdb/. All methods degrade gracefully:
    a sqlite error is logged and treated as "no record" (search stays correct
    because detection is reactive — a still-exhausted account re-hits the quota
    signal and is re-marked).
    """

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path
        self._resolved: Optional[Path] = None

    def _path(self) -> Optional[Path]:
        if self._db_path is not None:
            return self._db_path
        if self._resolved is not None:
            return self._resolved
        try:
            # Reverse import is safe: patentdb_store does not import gpss.
            from patent_mcp_server.patentdb_store import _resolve_db_root
            root = _resolve_db_root()
            root.mkdir(parents=True, exist_ok=True)
            self._resolved = root / _SIDECAR_FILENAME
            return self._resolved
        except Exception as e:  # noqa: BLE001
            logger.warning("GPSS quota sidecar path unresolved: %s", e)
            return None

    def _connect(self) -> Optional[sqlite3.Connection]:
        path = self._path()
        if path is None:
            return None
        try:
            conn = sqlite3.connect(str(path), timeout=5.0)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.executescript(_SCHEMA)
            return conn
        except Exception as e:  # noqa: BLE001
            logger.warning("GPSS quota sidecar connect failed (%s): %s", path, e)
            return None

    def mark_exhausted(self, account: str, key: Optional[str] = None) -> None:
        """Record `account` as exhausted for the current (or given) window."""
        if key is None:
            key = window_key()
        conn = self._connect()
        if conn is None:
            return
        try:
            conn.execute(
                "INSERT OR REPLACE INTO gpss_quota_exhausted "
                "(account, window_key, exhausted_at) VALUES (?, ?, ?)",
                (account, key, int(time.time())),
            )
            conn.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning("GPSS quota mark_exhausted failed: %s", e)
        finally:
            conn.close()

    def is_exhausted(self, account: str, key: Optional[str] = None) -> bool:
        """True IFF `account` is on record as exhausted for the current window.

        Records under a different (older) window_key do not match, so crossing a
        window boundary implicitly revives the account (DD-7).
        """
        if key is None:
            key = window_key()
        conn = self._connect()
        if conn is None:
            return False
        try:
            row = conn.execute(
                "SELECT 1 FROM gpss_quota_exhausted "
                "WHERE account = ? AND window_key = ? LIMIT 1",
                (account, key),
            ).fetchone()
            return row is not None
        except Exception as e:  # noqa: BLE001
            logger.warning("GPSS quota is_exhausted read failed: %s", e)
            return False
        finally:
            conn.close()

    def prune(self, keep_key: Optional[str] = None) -> None:
        """Best-effort cleanup: delete records for windows other than the current
        one. Not required for correctness (old keys never match a live query) —
        purely to keep the sidecar small. Safe to skip on any error."""
        if keep_key is None:
            keep_key = window_key()
        conn = self._connect()
        if conn is None:
            return
        try:
            conn.execute(
                "DELETE FROM gpss_quota_exhausted WHERE window_key != ?",
                (keep_key,),
            )
            conn.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning("GPSS quota prune failed: %s", e)
        finally:
            conn.close()
