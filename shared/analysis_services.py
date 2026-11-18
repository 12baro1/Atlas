"""Shared, strategy-neutral candle and indicator analysis services.

All helpers are pure over one supplied candle snapshot. Calls are memoized by
the active per-analysis context so independent strategies reuse identical work.
"""
from __future__ import annotations

import math
from statistics import median

from shared.analysis_context import cached_analysis


@cached_analysis
def _value(candle, name):
    try:
        value = float(getattr(candle, name))
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


@cached_analysis
def _series(candles, field="close"):
    """Return an aligned numeric series; never compress gaps in candle history."""
    sample = list(candles or [])
    if field == "close" and any(not _valid_ohlc(item) for item in sample):
        return []
    values = [_value(item, field) for item in sample]
    if any(value is None for value in values):
        return []
    return values


@cached_analysis
def _ema(values, period):
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1.0)
    result = sum(values[:period]) / period
    for value in values[period:]:
        result = alpha * value + (1.0 - alpha) * result
    return result


@cached_analysis
def _atr(candles, period=14):
    """Return Wilder-smoothed ATR using all available closed bars."""
    sample = list(candles or [])
    if period <= 0 or len(sample) < period + 1:
        return None
    ranges = []
    for previous, current in zip(sample[:-1], sample[1:]):
        high, low, prev_close = _value(current, "high"), _value(current, "low"), _value(previous, "close")
        if high is None or low is None or prev_close is None or high < low:
            return None
        ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    if len(ranges) < period:
        return None
    value = sum(ranges[:period]) / period
    for current_range in ranges[period:]:
        value = (value * (period - 1) + current_range) / period
    return value if value and math.isfinite(value) and value > 0 else None




@cached_analysis
def _adx(candles, period=14):
    """Return ADX using Wilder-smoothed TR/+DM/-DM and Wilder-smoothed DX."""
    sample = list(candles or [])
    if period <= 0 or len(sample) < period * 2 + 1:
        return None

    true_ranges, plus_dm, minus_dm = [], [], []
    for previous, current in zip(sample[:-1], sample[1:]):
        high, low = _value(current, "high"), _value(current, "low")
        prev_high, prev_low = _value(previous, "high"), _value(previous, "low")
        prev_close = _value(previous, "close")
        if None in (high, low, prev_high, prev_low, prev_close):
            return None
        if high < low or prev_high < prev_low:
            return None
        upward = high - prev_high
        downward = prev_low - low
        plus_dm.append(upward if upward > downward and upward > 0 else 0.0)
        minus_dm.append(downward if downward > upward and downward > 0 else 0.0)
        true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))

    if len(true_ranges) < period * 2:
        return None
    tr_smooth = sum(true_ranges[:period])
    plus_smooth = sum(plus_dm[:period])
    minus_smooth = sum(minus_dm[:period])
    dx_values = []
    for index in range(period - 1, len(true_ranges)):
        if index >= period:
            tr_smooth = tr_smooth - tr_smooth / period + true_ranges[index]
            plus_smooth = plus_smooth - plus_smooth / period + plus_dm[index]
            minus_smooth = minus_smooth - minus_smooth / period + minus_dm[index]
        if tr_smooth <= 0:
            return None
        plus_di = 100.0 * plus_smooth / tr_smooth
        minus_di = 100.0 * minus_smooth / tr_smooth
        denominator = plus_di + minus_di
        dx_values.append(100.0 * abs(plus_di - minus_di) / denominator if denominator > 0 else 0.0)
    if len(dx_values) < period:
        return None
    adx_value = sum(dx_values[:period]) / period
    for dx in dx_values[period:]:
        adx_value = (adx_value * (period - 1) + dx) / period
    return adx_value if math.isfinite(adx_value) else None


@cached_analysis
def _valid_ohlc(candle):
    """Reject malformed OHLC bars before they can create pivots or indicators."""
    values = [_value(candle, key) for key in ("open", "high", "low", "close")]
    if any(value is None or value <= 0 for value in values):
        return False
    opened, high, low, close = values
    return low <= min(opened, close) <= max(opened, close) <= high and high > low


@cached_analysis
def _candle_quality(candle):
    """Normalized candle anatomy; scale-invariant across symbols and prices."""
    opened, high, low, close = (_value(candle, key) for key in ("open", "high", "low", "close"))
    if None in (opened, high, low, close) or high <= low:
        return None
    span = high - low
    body = abs(close - opened)
    return {
        "body_ratio": body / span,
        "close_location": (close - low) / span,
        "upper_wick_ratio": (high - max(opened, close)) / span,
        "lower_wick_ratio": (min(opened, close) - low) / span,
        "range": span,
        "direction": "BULLISH" if close > opened else "BEARISH" if close < opened else "NEUTRAL",
    }


@cached_analysis
def _relative_volume(candles, lookback=20):
    """Last-bar volume relative to the median of preceding closed bars."""
    sample = list(candles or [])
    if len(sample) < lookback + 1:
        return None
    baseline = []
    for candle in sample[-(lookback + 1):-1]:
        value = _value(candle, "volume")
        if value is None or value < 0:
            return None
        baseline.append(value)
    current = _value(sample[-1], "volume")
    baseline_median = median(baseline) if baseline else 0.0
    if current is None or baseline_median <= 0:
        return None
    ratio = current / baseline_median
    return ratio if math.isfinite(ratio) else None


@cached_analysis
def _directional_movement(candles, period=14):
    """Return +DI/-DI using Wilder's seeded and recursively smoothed sums."""
    sample = list(candles or [])
    if period <= 0 or len(sample) < period + 1:
        return None
    true_ranges, plus_dm, minus_dm = [], [], []
    for previous, current in zip(sample[:-1], sample[1:]):
        high, low = _value(current, "high"), _value(current, "low")
        prev_high, prev_low = _value(previous, "high"), _value(previous, "low")
        prev_close = _value(previous, "close")
        if None in (high, low, prev_high, prev_low, prev_close):
            return None
        up, down = high - prev_high, prev_low - low
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    if len(true_ranges) < period:
        return None
    tr_smooth = sum(true_ranges[:period])
    plus_smooth = sum(plus_dm[:period])
    minus_smooth = sum(minus_dm[:period])
    for index in range(period, len(true_ranges)):
        tr_smooth = tr_smooth - tr_smooth / period + true_ranges[index]
        plus_smooth = plus_smooth - plus_smooth / period + plus_dm[index]
        minus_smooth = minus_smooth - minus_smooth / period + minus_dm[index]
    if tr_smooth <= 0:
        return None
    return {
        "plus_di": 100.0 * plus_smooth / tr_smooth,
        "minus_di": 100.0 * minus_smooth / tr_smooth,
        "method": "WILDER_SMOOTHED",
        "period": period,
    }


@cached_analysis
def _efficiency_ratio(values, period=20):
    """Kaufman-style directional efficiency, from 0 (chop) to 1 (one-way)."""
    if len(values) < period + 1:
        return None
    sample = values[-(period + 1):]
    path = sum(abs(right - left) for left, right in zip(sample, sample[1:]))
    if path <= 0:
        return 0.0
    result = abs(sample[-1] - sample[0]) / path
    return result if math.isfinite(result) else None


@cached_analysis
def _rsi(values, period=14):
    """Return Wilder RSI, seeded by the first period and recursively smoothed."""
    sample = [float(value) for value in (values or [])]
    if period <= 0 or len(sample) < period + 1 or any(not math.isfinite(v) for v in sample):
        return None
    changes = [right - left for left, right in zip(sample, sample[1:])]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period
    for index in range(period, len(changes)):
        average_gain = (average_gain * (period - 1) + gains[index]) / period
        average_loss = (average_loss * (period - 1) + losses[index]) / period
    if average_loss <= 0:
        return 100.0 if average_gain > 0 else 50.0
    relative_strength = average_gain / average_loss
    return 100.0 - 100.0 / (1.0 + relative_strength)




@cached_analysis
def _vwap(candles):
    numerator = denominator = 0.0
    for candle in candles or []:
        high, low, close = (_value(candle, key) for key in ("high", "low", "close"))
        volume = _value(candle, "volume")
        if None in (high, low, close, volume) or volume < 0:
            return None
        typical = (high + low + close) / 3.0
        numerator += typical * volume
        denominator += volume
    if denominator <= 0:
        return None
    value = numerator / denominator
    return value if math.isfinite(value) and value > 0 else None

@cached_analysis
def _bollinger(values, period=20, deviations=2.0):
    if len(values) < period:
        return None
    sample = values[-period:]
    mean = sum(sample) / period
    variance = sum((item - mean) ** 2 for item in sample) / period
    sigma = math.sqrt(max(0.0, variance))
    return mean - deviations * sigma, mean, mean + deviations * sigma


@cached_analysis
def _current_price(data):
    try:
        value = float(data.get("current_price"))
    except (TypeError, ValueError, OverflowError):
        value = None
    if value is not None and math.isfinite(value) and value > 0:
        return value
    candles = data.get("15m") or []
    return _value(candles[-1], "close") if candles else None


@cached_analysis
def _entry_reference(data):
    return str(data.get("current_price_source") or "LAST_CLOSED_15M_FALLBACK")
