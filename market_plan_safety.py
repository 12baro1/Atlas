"""Conservative, public-data preflight for actionable Gate.io MARKET setups.

This is a pre-publication / pre-display guard, not a claim that an order filled.
The 1m candle containing the signal time is intentionally included: because
OHLC does not reveal the intraminute order of events, a stop touch is unsafe.
"""
from __future__ import annotations

import math
import time

from config import Config
from execution_costs import estimate_plan_cost, estimate_stop_cost

MINUTE = 60_000
MAX_MARKET_SIGNAL_AGE_MS = 120_000
MAX_TICKER_AGE_MS = 15_000


def _positive_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def market_entry_distance_ok(planned, actual):
    planned, actual = _positive_number(planned), _positive_number(actual)
    limit = float(Config.MAX_MARKET_ENTRY_DISTANCE_PERCENT)
    return planned is not None and actual is not None and abs(actual - planned) / planned <= limit


def market_entry_risk_valid(direction, planned, actual, stop, tp1, costs):
    """Recheck the existing stop and first target at the actual entry price."""
    if not market_entry_distance_ok(planned, actual):
        return False
    actual, stop, tp1 = _positive_number(actual), _positive_number(stop), _positive_number(tp1)
    if None in (actual, stop, tp1):
        return False
    if not ((direction == "LONG" and stop < actual < tp1)
            or (direction == "SHORT" and tp1 < actual < stop)):
        return False
    risk = abs(actual - stop)
    if risk / actual < float(Config.MIN_STOP_PERCENT):
        return False
    cost_rates = {
        key: costs.get(key, default)
        for key, default in (
            ("maker_fee_rate", Config.MAKER_FEE_RATE), ("taker_fee_rate", Config.TAKER_FEE_RATE),
            ("spread_rate", Config.STOP_SPREAD_BUFFER_RATE), ("slippage_rate", Config.STOP_SLIPPAGE_BUFFER_RATE),
        )
    }
    stop_cost = estimate_stop_cost(actual, stop, entry_type="MARKET", **cost_rates)
    max_stop_cost_r = float(Config.MAX_STOP_EXECUTION_COST_R)
    if max_stop_cost_r > 0 and stop_cost["total"] / risk > max_stop_cost_r:
        return False
    if Config.MIN_TP1_RR <= 0:
        return True
    target_cost = estimate_plan_cost(
        actual, {"tp1": tp1}, {"tp1": 1.0}, entry_type="MARKET", **cost_rates
    )
    stop_exit_cost = max(0.0, stop_cost["total"] - stop_cost["entry_fee"])
    net_tp1_rr = (abs(tp1 - actual) - target_cost["total"]) / (risk + stop_exit_cost)
    return net_tp1_rr >= Config.MIN_TP1_RR


def stop_breached(direction, stop, low, high):
    """Inclusive stop touch; never infer an intraminute reversal as safe."""
    if direction == "LONG":
        return low <= stop
    if direction == "SHORT":
        return high >= stop
    return True


def check_market_plan(exchange, symbol, direction, entry, stop, signal_ms, *, tp1=None, costs=None, now_ms=None):
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
        if not market_entry_distance_ok(entry, latest):
            return False, "MARKET_ENTRY_PRICE_STALE"

        start = signal_time // MINUTE * MINUTE
        bars = exchange.fetch_ohlcv(symbol, "1m", since=start, limit=4) or []
        if not bars:
            return False, "MARKET_1M_HISTORY_UNAVAILABLE"
        observed_minutes = set()
        for bar in bars:
            try:
                ts, high, low = int(bar[0]), float(bar[2]), float(bar[3])
            except (TypeError, ValueError, IndexError, OverflowError):
                return False, "MARKET_1M_HISTORY_INVALID"
            if not (0 < low <= high and math.isfinite(low) and math.isfinite(high)):
                return False, "MARKET_1M_HISTORY_INVALID"
            if ts < start or ts > checked:
                continue
            if ts % MINUTE:
                return False, "MARKET_1M_HISTORY_INVALID"
            observed_minutes.add(ts)
            if stop_breached(direction, stop, low, high):
                return False, "MARKET_STOP_ALREADY_HIT"
        last_required = max(start, (stamp // MINUTE - 1) * MINUTE)
        if not set(range(start, last_required + MINUTE, MINUTE)).issubset(observed_minutes):
            return False, "MARKET_1M_HISTORY_GAP"
        finished = int(time.time() * 1000) if now_ms is None else now
        if finished - signal_time > MAX_MARKET_SIGNAL_AGE_MS:
            return False, "MARKET_SIGNAL_EXPIRED"
        if finished - stamp > MAX_TICKER_AGE_MS:
            return False, "MARKET_TICKER_UNAVAILABLE"
        if tp1 is not None and not market_entry_risk_valid(direction, entry, latest, stop, tp1, costs or {}):
            return False, "MARKET_ENTRY_QUALITY_REJECTED"
    except Exception:
        return False, "MARKET_VERIFICATION_UNAVAILABLE"
    return True, "MARKET_FRESH_CONFIRMED"
