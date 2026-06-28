"""Soft scrape policy — a per-host throttle for self-built crawler surfaces.

A SoftScrapePolicy makes "soft batch" crawling possible: serialize every request
to a host (Concurrency=1), pace each request by a random delay, and park a
cooldown after the host signals a block (429/503). It does NOT drop or rate-limit
requests away — it only SERIALIZES + PACES + PARKS so a batch trickles instead of
bursting, minimizing the chance of tripping a WAF / anti-bot challenge.

Taxonomy (binding contract — do NOT read these as anything looser):

  SoftScrapePolicy
    - what:   one throttle object per crawled host (e.g. TIPO GPSS, USPTO ppubs)
    - inputs: name, min_delay, max_delay, cooldown_default_s (all seconds)
    - holds:  a single asyncio.Lock (single-flight) + an active-cooldown deadline
    - NOT:    a token-bucket rate limiter, a retry engine, or a request dropper

  .guard()            async context manager. On enter: acquire the lock, then
                      wait out any active cooldown, then pace (sleep a random
                      [min,max]); yields with the lock HELD; releases on exit.
                      This is the single serialization primitive every scrape
                      burst goes through. NOT reentrant (asyncio.Lock) — never
                      nest .guard() within an already-held .guard() on the same
                      policy (that would deadlock).
  .delay()            sleep a random [min_delay,max_delay]. Standalone pacing for
                      callers that manage the lock themselves. NOT a cooldown.
  .park_cooldown(s)   set the active-cooldown deadline to now+s (default
                      cooldown_default_s). The NEXT .guard() enter waits it out.
                      NOT an immediate sleep — it only affects the next entry.
  .note_block(text)   convenience: log the block + park the default cooldown.
                      Call after observing a 429/503/challenge. NOT a raiser.
  .cooldown_remaining float seconds left on the active cooldown (0.0 if none).
                      Read-only signal. NOT a side-effecting call.

Single-process async server -> asyncio.Lock is sufficient (no multiprocessing).
"""

import asyncio
import logging
import random
import time
from contextlib import asynccontextmanager
from typing import Optional

logger = logging.getLogger(__name__)


class SoftScrapePolicy:
    def __init__(
        self,
        name: str,
        min_delay: float = 1.0,
        max_delay: float = 3.0,
        cooldown_default_s: float = 60.0,
    ):
        self.name = name
        if max_delay < min_delay:
            min_delay, max_delay = max_delay, min_delay
        self.min_delay = float(min_delay)
        self.max_delay = float(max_delay)
        self.cooldown_default_s = float(cooldown_default_s)
        self.lock = asyncio.Lock()
        self._cooldown_until = 0.0  # monotonic deadline; 0 == no active cooldown

    @property
    def cooldown_remaining(self) -> float:
        return max(self._cooldown_until - time.monotonic(), 0.0)

    async def delay(self) -> None:
        """Sleep a random [min_delay, max_delay]. Standalone pacing."""
        d = random.uniform(self.min_delay, self.max_delay)
        logger.debug("[%s] scrape pacing %.2fs", self.name, d)
        await asyncio.sleep(d)

    def park_cooldown(self, seconds: Optional[float] = None) -> None:
        """Park a cooldown the NEXT guard() enter must wait out."""
        s = self.cooldown_default_s if seconds is None else float(seconds)
        self._cooldown_until = time.monotonic() + s
        logger.warning("[%s] cooldown parked for %.0fs", self.name, s)

    def note_block(self, detail: str = "", seconds: Optional[float] = None) -> None:
        """Observe a host block (429/503/challenge): log + park default cooldown."""
        logger.error("[%s] host block observed (%s); parking cooldown", self.name, detail)
        self.park_cooldown(seconds)

    @asynccontextmanager
    async def guard(self):
        """Serialize + wait-out-cooldown + pace. Yields with the lock held.

        NOT reentrant — do not nest on the same policy (asyncio.Lock deadlock).
        """
        async with self.lock:
            remaining = self.cooldown_remaining
            if remaining > 0:
                logger.info("[%s] waiting out %.1fs cooldown before request", self.name, remaining)
                await asyncio.sleep(remaining)
            await self.delay()
            yield
