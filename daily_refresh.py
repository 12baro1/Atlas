"""Daily pool refresh at 00:00 Europe/Istanbul (requirement K).

One idempotent operation per calendar day (Istanbul time):
1. The previous day's pool state is archived (SQLite backup + DAILY_REFRESH
   history rows); old records are preserved, never deleted.
2. A new daily pool period opens: candidates and validated pools are
   cleared for the new day; user-accepted active setups are kept.
3. The scan queue is prepared for the new period: the current Gate.io
   universe is re-enqueued (existing job states are preserved by design).

State (last_refresh_day) lives in the pool's SQLite meta table, so a VPS
restart cannot double-refresh the same day. UTC timestamps are stored;
Europe/Istanbul is only used to decide "today".
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

try:
    from zoneinfo import ZoneInfo
    ISTANBUL = ZoneInfo("Europe/Istanbul")
except Exception:  # pragma: no cover - fallback keeps UTC semantics
    ISTANBUL = timezone.utc

logger = logging.getLogger("atlas.daily_refresh")

REFRESH_HOUR_IST = 0  # 00:00 Europe/Istanbul


def istanbul_day(now_utc_ms: Optional[int] = None) -> str:
    """Calendar date (YYYY-MM-DD) in Europe/Istanbul for a UTC ms timestamp."""
    moment = datetime.fromtimestamp(
        (now_utc_ms if now_utc_ms is not None else time.time() * 1000) / 1000.0,
        tz=timezone.utc,
    )
    return moment.astimezone(ISTANBUL).strftime("%Y-%m-%d")


def istanbul_hour(now_utc_ms: Optional[int] = None) -> int:
    moment = datetime.fromtimestamp(
        (now_utc_ms if now_utc_ms is not None else time.time() * 1000) / 1000.0,
        tz=timezone.utc,
    )
    return moment.astimezone(ISTANBUL).hour


class DailyPoolRefresh:
    """Runs at most one pool refresh per Istanbul calendar day."""

    def __init__(self, pool, scan_queue, market_inventory, refresh_hour: int = REFRESH_HOUR_IST):
        self.pool = pool
        self.scan_queue = scan_queue
        self.market_inventory = market_inventory
        self.refresh_hour = int(refresh_hour)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Core operation
    # ------------------------------------------------------------------

    def last_refresh_day(self) -> Optional[str]:
        try:
            store = getattr(self.pool, "_store", None)
            if store is not None:
                return store.get_meta("last_refresh_day")
        except Exception as exc:
            logger.error(f"Could not read last_refresh_day: {exc}")
        return None

    def run_if_due(self, now_utc_ms: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Refresh when the Istanbul hour allows and the day has not been done.

        Idempotent: the last_refresh_day marker in SQLite makes a repeat call
        for the same day a no-op, so restarts and retry loops are safe.
        """
        now_ms = int(now_utc_ms if now_utc_ms is not None else time.time() * 1000)
        with self._lock:
            if istanbul_hour(now_ms) < self.refresh_hour:
                return None
            today = istanbul_day(now_ms)
            if self.last_refresh_day() == today:
                return None
            try:
                inventory = self.market_inventory.status()
                universe = self.market_inventory.get_symbols()
                counts = self.pool.archive_and_reset_scan_pools(today)
                # New period: make sure the whole current universe is queued
                # for scanning. Existing job states are preserved by the
                # queue (no silent reset of completed work).
                queue_result = self.scan_queue.rebuild(universe)
                store = getattr(self.pool, "_store", None)
                if store is not None:
                    store.set_meta("last_refresh_day", today)
                result = {
                    "day": today,
                    "archived_candidates": counts["candidates"],
                    "archived_validated": counts["validated"],
                    "universe_size": len(universe),
                    "queue_added": queue_result["added"],
                    "inventory_last_refresh_ms": inventory.get("last_refresh_ms"),
                }
                logger.info(f"Daily pool refresh completed for {today}: {result}")
                return result
            except Exception as exc:
                logger.error(f"Daily pool refresh failed: {exc}")
                return None

    # ------------------------------------------------------------------
    # Scheduling thread (independent of Telegram lifecycle)
    # ------------------------------------------------------------------

    def start_background(self, check_interval_seconds: int = 60):
        """Start a daemon thread that runs the refresh when it comes due.

        The thread re-checks every interval, so a VPS restart shortly after
        00:00 still performs the pending refresh on the next tick.
        """
        def loop():
            while not self._stop_event.is_set():
                try:
                    self.run_if_due()
                except Exception as exc:  # pragma: no cover
                    logger.error(f"Daily refresh loop error: {exc}")
                if self._stop_event.wait(max(10, int(check_interval_seconds))):
                    break

        self._thread = threading.Thread(target=loop, daemon=True, name="AtlasDailyRefresh")
        self._thread.start()
        return self._thread

    def stop(self, timeout: float = 5.0):
        """Stop the background refresh thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(0.0, timeout))
            self._thread = None
