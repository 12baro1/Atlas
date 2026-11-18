"""Independent mean_reversion setup generator. Strategy logic lives in this package."""


def generate(data, regime):
    from strategy_lab import _series, _atr, _bollinger, _rsi, statistical_deviation, rsi_divergence, _value, _candle_quality, _current_price, _vwap, _raw_candidate, _entry_reference, _strategy_specialist_evidence, _attach_strategy_specialist_evidence
    specialist_evidence = _strategy_specialist_evidence(data, "mean_reversion")
    candles = data.get("15m") or []
    closes = _series(candles)
    atr = _atr(candles)
    bands = _bollinger(closes)
    rsi = _rsi(closes)
    if regime.get("label") not in {"RANGE", "TRANSITION"} or (regime.get("label") == "TRANSITION" and float(regime.get("adx") or 0.0) > 20.0) or len(candles) < 25 or atr is None or bands is None or rsi is None:
        return None
    previous_bands = _bollinger(closes[:-1])
    previous_rsi = _rsi(closes[:-1])
    deviation_evidence = statistical_deviation(closes, 20)
    divergence_evidence = rsi_divergence(candles, [_rsi(closes[:i+1]) for i in range(len(closes))])
    if previous_bands is None or previous_rsi is None:
        return None
    lower, _, upper = bands
    prev_lower, _, prev_upper = previous_bands
    previous, last = candles[-2], candles[-1]
    prev_close, close = _value(previous, "close"), _value(last, "close")
    quality = _candle_quality(last)
    if None in (prev_close, close) or quality is None:
        return None
    direction = None
    if (prev_close < prev_lower and close > lower and rsi <= 45
            and rsi > previous_rsi and quality["direction"] == "BULLISH"
            and quality["lower_wick_ratio"] >= 0.15 and quality["close_location"] >= 0.55):
        direction = "LONG"
    elif (prev_close > prev_upper and close < upper and rsi >= 55
            and rsi < previous_rsi and quality["direction"] == "BEARISH"
            and quality["upper_wick_ratio"] >= 0.15 and quality["close_location"] <= 0.45):
        direction = "SHORT"
    else:
        return None
    entry = _current_price(data)
    vwap = _vwap(candles[-20:])
    if entry is None or vwap is None:
        return None
    middle = bands[1]
    vwap_distance_atr = abs(entry - vwap) / atr
    if direction == "LONG":
        if not lower <= entry <= middle or entry >= vwap or not 0.15 <= vwap_distance_atr <= 3.0:
            return None
    else:
        if not middle <= entry <= upper or entry <= vwap or not 0.15 <= vwap_distance_atr <= 3.0:
            return None
    extremity = max(0.0, 42.0 - rsi) if direction == "LONG" else max(0.0, rsi - 58.0)
    strength = min(88.0, 65.0 + min(extremity * 0.5, 12.0) + min(abs(close - prev_close) / atr * 4.0, 8.0))
    # _valid_plan in common filter computes structural stop; pass dummy stop (ignored)
    dummy_stop = entry - atr if direction == "LONG" else entry + atr
    plan = _raw_candidate(direction, entry, dummy_stop, atr, "mean_reversion", strength, entry_reference=_entry_reference(data))
    if plan:
        rejection_wick = quality["lower_wick_ratio"] if direction == "LONG" else quality["upper_wick_ratio"]
        plan["reasons"] = [
            "15m Bollinger outside-close re-entry in a classified range regime",
            f"RSI14={rsi:.1f} turning from {previous_rsi:.1f}",
            f"VWAP deviation={vwap_distance_atr:.2f} ATR with mean-side confirmation",
            f"Rejection wick={rejection_wick:.2f}; close-location={quality['close_location']:.2f}",
        ]
        plan["mean_reversion_metrics"] = {"rsi": round(rsi, 2), "prior_rsi": round(previous_rsi, 2),
                                          "vwap_distance_atr": round(vwap_distance_atr, 3),
                                          "rejection_wick_ratio": round(rejection_wick, 3),
                                          "statistical_deviation": deviation_evidence, "rsi_divergence": divergence_evidence}
    if plan:
        _attach_strategy_specialist_evidence(plan, specialist_evidence)
    return plan

