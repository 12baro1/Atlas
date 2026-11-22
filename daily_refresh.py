"""Daily pool refresh at 00:00 Europe/Istanbul (requirement K).

One idempotent operation per calendar day (Istanbul time):
1. Archive the pool with a SQLite backup. Keep live setups for revalidation.
2. Resume existing scan work or enqueue the ranked Gate.io universe when drained.

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
from scan_service import DEFAULT_SCAN_UNIVERSE_LIMIT

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

    def __init__(self, pool, scan_queue, market_inventory, refresh_hour: int = REFRESH_HOUR_IST, *, continuous=False):
        self.continuous = continuous
        self.scan_allowed = threading.Event()
        self.scan_allowed.set()
        self.pool = pool
        self.scan_queue = scan_queue
        self.market_inventory = market_inventory
        self.refresh_hour = int(refresh_hour)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._live_thread: Optional[threading.Thread] = None

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
            if self.continuous:
                return {"cleaned": True} if self.pool.clean_published_if_due(now_ms) else None
            if istanbul_hour(now_ms) < self.refresh_hour:
                return None
            today = istanbul_day(now_ms)
            if self.last_refresh_day() == today:
                return None
            try:
                inventory = self.market_inventory.status()
                ranker = getattr(self.market_inventory, "get_ranked_symbols", None)
                if callable(ranker):
                    universe = list(ranker(limit=DEFAULT_SCAN_UNIVERSE_LIMIT) or [])
                else:
                    universe = sorted(self.market_inventory.get_symbols())[:DEFAULT_SCAN_UNIVERSE_LIMIT]
                if not universe:
                    return None
                counts = self.pool.archive_and_reset_scan_pools(today)
                # The queue decides under the SQLite write lock whether to roll over.
                queue_result = self.scan_queue.rebuild(
                    universe, batch_tag=f"refresh_{today}", preserve_unfinished=True,
                    ranking_source=inventory.get("ranking_source", "unknown")
                )
                store = getattr(self.pool, "_store", None)
                if store is not None:
                    store.set_meta("last_refresh_day", today)
                result = {
                    "day": today,
                    "scan_generation": queue_result.get("generation"),
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

    def refresh_virtual_positions(self):
        from tracking_history import TrackingHistory
        self.scan_allowed.clear()
        try:
            symbols = self.pool.tracking.open_symbols(due_only=True)
            if not symbols:
                return
            history = TrackingHistory()
            try:
                for symbol in symbols:
                    if self._stop_event.is_set():
                        break
                    try:
                        self.pool.tracking.advance_tracking(symbol, history=history)
                    except Exception as exc:
                        logger.warning("Virtual position data unavailable for %s (%s)", symbol, type(exc).__name__)
            finally:
                history.exchange.session.close()
        finally:
            self.scan_allowed.set()

    def start_background(self, check_interval_seconds: int = 60):
        """Start a daemon thread that runs the refresh when it comes due.

        The thread re-checks every interval, so a VPS restart shortly after
        00:00 still performs the pending refresh on the next tick.
        """
        def maintenance():
            if self.continuous:
                try:
                    self.refresh_virtual_positions()
                except Exception:
                    logger.exception("Virtual position refresh failed")
                if not self._stop_event.is_set():
                    try:
                        self.pool.tracking.refresh_closed_targets()
                    except Exception:
                        logger.exception("Closed target observation failed")
            try:
                self.run_if_due()
            except Exception as exc:  # pragma: no cover
                logger.error(f"Daily refresh loop error: {exc}")

        def loop():
            interval = max(10, int(check_interval_seconds))
            while not self._stop_event.is_set():
                maintenance()
                self._stop_event.wait(interval)

        def live_loop():
            from functools import partial
            from types import SimpleNamespace

            from gateio_tracking_stream import GateTrackingStream
            from tracking_history import TrackingHistory

            history = TrackingHistory()
            stream = GateTrackingStream()
            fallback_due = 0
            stream.start()
            try:
                while not self._stop_event.is_set():
                    try:
                        stream.follow(self.pool.tracking.live_trade_symbols())
                        fallback = None
                        if time.monotonic() >= fallback_due:
                            fallback = history.trade_range
                            fallback_due = time.monotonic() + 5
                        source = SimpleNamespace(trade_range=partial(stream.trade_range, fallback=fallback))
                        self.pool.tracking.refresh_live_trades(source, self._stop_event)
                    except Exception:
                        logger.exception("Live position refresh failed")
                    self._stop_event.wait(1)
            finally:
                stream.stop()
                history.exchange.session.close()

        self._thread = threading.Thread(target=loop, daemon=True, name="AtlasDailyRefresh")
        if self.continuous:
            self.scan_allowed.clear()
        try:
            self._thread.start()
            if self.continuous:
                self._live_thread = threading.Thread(target=live_loop, daemon=True, name="AtlasLiveTracking")
                self._live_thread.start()
        except RuntimeError:
            self.scan_allowed.set()
            raise
        return self._thread

    def stop(self, timeout: float = 5.0) -> bool:
        """Stop the background refresh thread without losing a live thread reference."""
        self._stop_event.set()
        deadline = time.monotonic() + max(0.0, float(timeout))
        for attribute in ("_thread", "_live_thread"):
            thread = getattr(self, attribute)
            if thread and thread.is_alive():
                thread.join(timeout=max(0.0, deadline - time.monotonic()))
            if thread and not thread.is_alive():
                setattr(self, attribute, None)
        return self._thread is None and self._live_thread is None
