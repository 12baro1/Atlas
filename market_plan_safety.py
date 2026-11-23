"""Conservative, public-data preflight for actionable Gate.io MARKET setups.

This is a pre-publication / pre-display guard, not a claim that an order filled.
The 1m candle containing the signal time is intentionally included: because
OHLC does not reveal the intraminute order of events, a stop touch is unsafe.
"""
from __future__ import annotations

import math
import time

from config import Config

MINUTE = 60_000
MAX_MARKET_SIGNAL_AGE_MS = 120_000
MAX_TICKER_AGE_MS = 15_000


def _positive_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def stop_breached(direction, stop, low, high):
    """Inclusive stop touch; never infer an intraminute reversal as safe."""
    if direction == "LONG":
        return low <= stop
    if direction == "SHORT":
        return high >= stop
    return True


def check_market_plan(exchange, symbol, direction, entry, stop, signal_ms, *, now_ms=None):
    """Return (is_actionable, reason), failing closed on missing market evidence.

    Caller supplies a newly produced or still-actionable stored MARKET plan.
    One fresh ticker and bounded 1m OHLCV range are required. Only 2m-old or
    newer entry signals qualify; unchanged historical MARKETs must not be
    advertised as fresh opportunities indefinitely.
    """
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    try:
        signal_time = int(signal_ms)
    except (TypeError, ValueError, OverflowError):
        return False, "MARKET_SIGNAL_TIME_UNKNOWN"
    if signal_time <= 0 or signal_time > now or now - signal_time > MAX_MARKET_SIGNAL_AGE_MS:
        return False, "MARKET_SIGNAL_EXPIRED"
    if direction not in {"LONG", "SHORT"}:
        return False, "MARKET_DIRECTION_INVALID"
    entry, stop = _positive_number(entry), _positive_number(stop)
    if entry is None or stop is None:
        return False, "MARKET_PRICES_INVALID"
    if (direction == "LONG" and stop >= entry) or (direction == "SHORT" and stop <= entry):
        return False, "MARKET_GEOMETRY_INVALID"

    try:
        ticker = exchange.fetch_ticker(symbol) or {}
        latest = _positive_number(ticker.get("last"))
        stamp = int(ticker.get("timestamp") or 0)
        checked = int(time.time() * 1000) if now_ms is None else now
        if latest is None or not 0 <= checked - stamp <= MAX_TICKER_AGE_MS:
            return False, "MARKET_TICKER_UNAVAILABLE"
        if stop_breached(direction, stop, latest, latest):
            return False, "MARKET_STOP_ALREADY_HIT"
        drift = abs(latest - entry) / entry
        if drift > float(getattr(Config, "MAX_MARKET_ENTRY_DISTANCE_PERCENT", 0.003)):
            return False, "MARKET_ENTRY_PRICE_STALE"

        start = signal_time // MINUTE * MINUTE
        bars = exchange.fetch_ohlcv(symbol, "1m", since=start, limit=4) or []
        if not bars:
            return False, "MARKET_1M_HISTORY_UNAVAILABLE"
        valid_latest = 0
        for bar in bars:
            try:
                ts, high, low = int(bar[0]), float(bar[2]), float(bar[3])
            except (TypeError, ValueError, IndexError, OverflowError):
                return False, "MARKET_1M_HISTORY_INVALID"
            if not (0 < low <= high and math.isfinite(low) and math.isfinite(high)):
                return False, "MARKET_1M_HISTORY_INVALID"
            if ts < start or ts > checked:
                continue
            valid_latest = max(ts, valid_latest)
            if stop_breached(direction, stop, low, high):
                return False, "MARKET_STOP_ALREADY_HIT"
        if not valid_latest or checked - valid_latest > 2 * MINUTE:
            return False, "MARKET_1M_HISTORY_STALE"
    except Exception:
        return False, "MARKET_VERIFICATION_UNAVAILABLE"
    return True, "MARKET_FRESH_CONFIRMED"
