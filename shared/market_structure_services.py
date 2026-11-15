"""Shared, strategy-neutral market-structure evidence services.

These helpers report market evidence only. They never create setups, veto other
strategies, or make portfolio decisions.
"""
from __future__ import annotations

import math
from statistics import median

from shared.analysis_context import cached_analysis


import math
from statistics import median


@cached_analysis
def _number(candle, field):
    try:
        value = float(getattr(candle, field))
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


@cached_analysis
def trend_structure(candles, lookback=80):
    """Classify confirmed two-left/two-right swing progression."""
    bars = list(candles or [])[-lookback:]
    if len(bars) < 12:
        return {"state": "UNKNOWN", "higher_highs": 0, "higher_lows": 0,
                "lower_highs": 0, "lower_lows": 0, "quality": 0.0}
    highs, lows = [], []
    for i in range(2, len(bars) - 2):
        h, l = _number(bars[i], "high"), _number(bars[i], "low")
        window_h = [_number(x, "high") for x in bars[i-2:i] + bars[i+1:i+3]]
        window_l = [_number(x, "low") for x in bars[i-2:i] + bars[i+1:i+3]]
        if h is None or l is None or any(x is None for x in window_h + window_l):
            return {"state": "INVALID_DATA", "higher_highs": 0, "higher_lows": 0,
                    "lower_highs": 0, "lower_lows": 0, "quality": 0.0}
        if h > max(window_h): highs.append(h)
        if l < min(window_l): lows.append(l)
    hh = sum(b > a for a, b in zip(highs, highs[1:]))
    lh = sum(b < a for a, b in zip(highs, highs[1:]))
    hl = sum(b > a for a, b in zip(lows, lows[1:]))
    ll = sum(b < a for a, b in zip(lows, lows[1:]))
    if hh + hl >= 2 and hh >= 1 and hl >= 1: state = "BULLISH"
    elif lh + ll >= 2 and lh >= 1 and ll >= 1: state = "BEARISH"
    else: state = "MIXED"
    total = max(1, hh + hl + lh + ll)
    aligned = hh + hl if state == "BULLISH" else lh + ll if state == "BEARISH" else 0
    return {"state": state, "higher_highs": hh, "higher_lows": hl,
            "lower_highs": lh, "lower_lows": ll,
            "quality": round(aligned / total, 4)}


@cached_analysis
def displacement(candles, atr):
    """Measure last closed candle impulse against ATR; not a direction signal."""
    bars = list(candles or [])
    if not bars or not isinstance(atr, (int, float)) or not math.isfinite(atr) or atr <= 0:
        return {"state": "UNAVAILABLE"}
    bar = bars[-1]
    o, h, l, c = (_number(bar, k) for k in ("open", "high", "low", "close"))
    if None in (o, h, l, c) or h <= l or l > min(o, c) or max(o, c) > h:
        return {"state": "INVALID_DATA"}
    span = h - l
    body_atr = abs(c - o) / atr
    close_location = (c - l) / span
    direction = "BULLISH" if c > o else "BEARISH" if c < o else "NEUTRAL"
    quality = min(1.0, body_atr / 1.5) * (close_location if direction == "BULLISH" else 1-close_location if direction == "BEARISH" else 0.0)
    return {"state": "IMPULSE" if body_atr >= 0.8 and quality >= 0.45 else "ORDINARY",
            "direction": direction, "body_atr": round(body_atr, 4),
            "range_atr": round(span / atr, 4), "close_location": round(close_location, 4),
            "quality": round(quality, 4)}


@cached_analysis
def volatility_regime(candles, period=14, history=80):
    """Percentile rank of current Wilder-style ATR proxy within its own history."""
    bars = list(candles or [])
    if period <= 0 or len(bars) < period + 2:
        return {"state": "UNAVAILABLE", "atr_percentile": None}
    values = []
    start = max(period + 1, len(bars) - history)
    for end in range(start, len(bars) + 1):
        sample = bars[:end]
        trs = []
        for prev, cur in zip(sample[-(period+1):-1], sample[-period:]):
            h, l, pc = _number(cur, "high"), _number(cur, "low"), _number(prev, "close")
            if None in (h, l, pc) or h < l:
                return {"state": "INVALID_DATA", "atr_percentile": None}
            trs.append(max(h-l, abs(h-pc), abs(l-pc)))
        if len(trs) == period:
            values.append(sum(trs) / period)
    if len(values) < 10:
        return {"state": "UNAVAILABLE", "atr_percentile": None}
    current = values[-1]
    percentile = sum(v <= current for v in values) / len(values)
    state = "LOW" if percentile <= .2 else "HIGH" if percentile >= .8 else "NORMAL"
    return {"state": state, "atr_percentile": round(percentile, 4)}


@cached_analysis
def breakout_acceptance(candles, lookback=20):
    """Check whether last close accepts beyond the prior range boundary."""
    bars = list(candles or [])
    if len(bars) < lookback + 1:
        return {"state": "UNAVAILABLE"}
    prior = bars[-lookback-1:-1]
    highs = [_number(x, "high") for x in prior]
    lows = [_number(x, "low") for x in prior]
    last = bars[-1]
    o, h, l, c = (_number(last, k) for k in ("open", "high", "low", "close"))
    if any(x is None for x in highs + lows) or None in (o, h, l, c) or h < l:
        return {"state": "INVALID_DATA"}
    upper, lower = max(highs), min(lows)
    if c > upper:
        state, direction, distance = "ACCEPTED", "LONG", (c-upper)/max(upper, 1e-12)
    elif c < lower:
        state, direction, distance = "ACCEPTED", "SHORT", (lower-c)/max(lower, 1e-12)
    elif h > upper and c <= upper:
        state, direction, distance = "FAILED_UPSIDE", "NONE", 0.0
    elif l < lower and c >= lower:
        state, direction, distance = "FAILED_DOWNSIDE", "NONE", 0.0
    else:
        state, direction, distance = "INSIDE_RANGE", "NONE", 0.0
    return {"state": state, "direction": direction, "upper": upper,
            "lower": lower, "close": c, "distance_pct": round(distance, 6)}


@cached_analysis
def statistical_deviation(values, lookback=20):
    """Population z-score against preceding observations, excluding current."""
    sample = [float(x) for x in (values or [])]
    if len(sample) < lookback + 1 or any(not math.isfinite(x) for x in sample):
        return {"state": "UNAVAILABLE", "zscore": None}
    baseline = sample[-lookback-1:-1]
    mean = sum(baseline) / lookback
    variance = sum((x-mean)**2 for x in baseline) / lookback
    sigma = math.sqrt(variance)
    if sigma <= 0:
        if sample[-1] == mean:
            return {"state": "FLAT", "zscore": 0.0, "mean": mean, "sigma": 0.0}
        return {"state": "EXTREME", "zscore": None,
                "direction": "ABOVE_MEAN" if sample[-1] > mean else "BELOW_MEAN",
                "mean": mean, "sigma": 0.0}
    z = (sample[-1]-mean)/sigma
    return {"state": "EXTREME" if abs(z) >= 2 else "NORMAL",
            "zscore": round(z, 4), "mean": mean, "sigma": sigma}


@cached_analysis
def rsi_divergence(candles, rsi_values, lookback=40):
    """Detect regular divergence using confirmed local price/RSI pivots."""
    bars = list(candles or [])[-lookback:]
    rsis = list(rsi_values or [])[-lookback:]
    if len(bars) != len(rsis) or len(bars) < 9 or any(x is not None and (not isinstance(x, (int,float)) or not math.isfinite(x)) for x in rsis):
        return {"state": "UNAVAILABLE"}
    lows, highs = [], []
    for i in range(2, len(bars)-2):
        h, l = _number(bars[i], "high"), _number(bars[i], "low")
        hs = [_number(x, "high") for x in bars[i-2:i] + bars[i+1:i+3]]
        ls = [_number(x, "low") for x in bars[i-2:i] + bars[i+1:i+3]]
        if h is None or l is None or any(x is None for x in hs+ls):
            return {"state": "INVALID_DATA"}
        if rsis[i] is None:
            continue
        if l < min(ls): lows.append((l, rsis[i]))
        if h > max(hs): highs.append((h, rsis[i]))
    if len(lows) >= 2 and lows[-1][0] < lows[-2][0] and lows[-1][1] > lows[-2][1]:
        return {"state": "BULLISH_REGULAR", "price_pivots": [lows[-2][0], lows[-1][0]],
                "rsi_pivots": [lows[-2][1], lows[-1][1]]}
    if len(highs) >= 2 and highs[-1][0] > highs[-2][0] and highs[-1][1] < highs[-2][1]:
        return {"state": "BEARISH_REGULAR", "price_pivots": [highs[-2][0], highs[-1][0]],
                "rsi_pivots": [highs[-2][1], highs[-1][1]]}
    return {"state": "NONE"}
