"""Independent trend_pullback setup generator. Strategy logic lives in this package."""

from shared.analysis_services import (
    _value,
    _series,
    _atr,
    _ema,
    _adx,
    _directional_movement,
    _candle_quality,
    _efficiency_ratio,
    _current_price,
    _entry_reference,
)
from shared.market_structure_services import trend_structure, displacement
from strategies.candidate import _raw_candidate
from shared.specialist_evidence import evidence_for_strategy, attach_strategy_evidence


def generate(data):
    specialist_evidence = evidence_for_strategy(data, "trend_pullback")
    h4, h1 = data.get("4h") or [], data.get("1h") or []
    c4, c1 = _series(h4), _series(h1)
    atr = _atr(h1)
    if len(c4) < 60 or len(c1) < 30 or atr is None:
        return None
    e20, e50, e1 = _ema(c4, 20), _ema(c4, 50), _ema(c1, 20)
    adx_value = _adx(h4)
    e20_previous = _ema(c4[:-5], 20)
    if None in (e20, e50, e1, adx_value, e20_previous):
        return None
    trend_slope = (e20 - e20_previous) / atr
    directional = _directional_movement(h4)
    last, previous = h1[-1], h1[-2]
    close = _value(last, "close")
    prev_close = _value(previous, "close")
    low, high = _value(last, "low"), _value(last, "high")
    prev_low, prev_high = _value(previous, "low"), _value(previous, "high")
    quality = _candle_quality(last)
    efficiency = _efficiency_ratio(c4, 20)
    if None in (close, prev_close, low, high, prev_low, prev_high) or quality is None or directional is None or efficiency is None:
        return None
    entry = _current_price(data)
    if entry is None:
        return None
    direction = None
    bullish_dmi = directional["plus_di"] > directional["minus_di"]
    bearish_dmi = directional["minus_di"] > directional["plus_di"]
    if (e20 > e50 and bullish_dmi and entry > e1 and entry <= e1 + 1.50 * atr
            and (low <= e1 * 1.005 or prev_low <= e1 * 1.003)
            and close > prev_close and quality["direction"] == "BULLISH"
            and quality["close_location"] >= 0.55 and quality["body_ratio"] >= 0.20):
        direction = "LONG"
    elif (e20 < e50 and bearish_dmi and entry < e1 and entry >= e1 - 1.50 * atr
            and (high >= e1 * 0.995 or prev_high >= e1 * 0.997)
            and close < prev_close and quality["direction"] == "BEARISH"
            and quality["close_location"] <= 0.45 and quality["body_ratio"] >= 0.20):
        direction = "SHORT"
    else:
        return None
    trend_separation = abs(e20 - e50) / atr
    pullback_distance = abs(entry - e1) / atr
    structure_evidence = trend_structure(h4)
    impulse_evidence = displacement(h1, atr)
    if (direction == "LONG" and trend_slope <= 0) or (direction == "SHORT" and trend_slope >= 0):
        return None
    strength = min(92.0, 60.0 + min(trend_separation * 5.0, 10.0)
                   + min((adx_value - 18.0) * 0.45, 9.0)
                   + min(efficiency * 10.0, 7.0)
                   + min(abs(directional["plus_di"] - directional["minus_di"]) * 0.15, 6.0)
                   + max(0.0, 7.0 - pullback_distance * 5.0))
    # Weak ADX lowers confidence rather than hiding a valid EMA/DMI reclaim.
    if adx_value < 16:
        strength = max(0.0, strength - 10.0)
    # _valid_plan in common filter computes structural stop; pass dummy stop (ignored)
    dummy_stop = entry - atr if direction == "LONG" else entry + atr
    plan = _raw_candidate(direction, entry, dummy_stop, atr, "trend_pullback", strength, entry_reference=_entry_reference(data))
    if plan:
        plan["reasons"] = [
            f"4H EMA20/EMA50 trend alignment; EMA20 slope={trend_slope:.2f} ATR",
            f"4H ADX={adx_value:.1f}; +DI={directional['plus_di']:.1f}; -DI={directional['minus_di']:.1f}",
            f"4H directional efficiency={efficiency:.2f}",
            f"1H EMA20 pullback reclaim; body={quality['body_ratio']:.2f}; close-location={quality['close_location']:.2f}",
        ]
        plan["trend_metrics"] = {"adx": round(adx_value, 2), **{key: round(value, 2) for key, value in directional.items() if isinstance(value, (int, float))},
                                 "efficiency_ratio": round(efficiency, 3), "pullback_distance_atr": round(pullback_distance, 3),
                                 "structure": structure_evidence, "displacement": impulse_evidence}
        plan["reasons"].append(f"Structure motor={structure_evidence['state']} (quality={structure_evidence['quality']:.2f}); displacement={impulse_evidence.get('state')}")
    if plan:
        attach_strategy_evidence(plan, specialist_evidence)
    return plan

