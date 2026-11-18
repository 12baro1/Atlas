"""Independent volatility_breakout setup generator. Strategy logic lives in this package."""


def generate(data):
    from strategy_lab import _series, _atr, _bollinger, volatility_regime, breakout_acceptance, _value, _candle_quality, _relative_volume, _current_price, _raw_candidate, _entry_reference, _strategy_specialist_evidence, _attach_strategy_specialist_evidence
    specialist_evidence = _strategy_specialist_evidence(data, "volatility_breakout")
    candles = data.get("1h") or []
    closes = _series(candles)
    atr = _atr(candles)
    if len(candles) < 45 or atr is None:
        return None
    # Require pre-breakout volatility compression; the current breakout bar
    # must close outside the prior range, not merely wick through it.
    bandwidths = []
    for end in range(max(20, len(closes) - 41), len(closes) - 1):
        band = _bollinger(closes[end - 20:end])
        if band:
            bandwidths.append((band[2] - band[0]) / max(band[1], 1e-12))
    prior_band = _bollinger(closes[-21:-1])
    volatility_evidence = volatility_regime(candles)
    breakout_evidence = breakout_acceptance(candles, 20)
    if not bandwidths or prior_band is None:
        return None
    prior_width = (prior_band[2] - prior_band[0]) / max(prior_band[1], 1e-12)
    compression_threshold = sorted(bandwidths)[max(0, int((len(bandwidths) - 1) * 0.50))]
    if prior_width > compression_threshold:
        return None
    previous = candles[-21:-1]
    last = candles[-1]
    prior_highs = [_value(item, "high") for item in previous]
    prior_lows = [_value(item, "low") for item in previous]
    close = _value(last, "close")
    quality = _candle_quality(last)
    volume_ratio = _relative_volume(candles, 20)
    if close is None or quality is None or volume_ratio is None or any(item is None for item in prior_highs + prior_lows):
        return None
    entry = _current_price(data)
    if entry is None:
        return None
    upper_boundary, lower_boundary = max(prior_highs), min(prior_lows)
    direction = None
    if (close > upper_boundary and breakout_evidence.get("state") == "ACCEPTED" and breakout_evidence.get("direction") == "LONG" and entry >= close and entry <= upper_boundary + atr
            and volume_ratio >= 1.15 and quality["direction"] == "BULLISH"
            and quality["body_ratio"] >= 0.40 and quality["close_location"] >= 0.65
            and quality["range"] >= 0.60 * atr):
        direction = "LONG"
    elif (close < lower_boundary and breakout_evidence.get("state") == "ACCEPTED" and breakout_evidence.get("direction") == "SHORT" and entry <= close and entry >= lower_boundary - atr
            and volume_ratio >= 1.30 and quality["direction"] == "BEARISH"
            and quality["body_ratio"] >= 0.50 and quality["close_location"] <= 0.35
            and quality["range"] >= 0.75 * atr):
        direction = "SHORT"
    else:
        return None
    boundary = upper_boundary if direction == "LONG" else lower_boundary
    breakout_distance = abs(entry - boundary) / atr
    strength = min(93.0, 61.0 + min(max(0.0, volume_ratio - 1.15) * 10.0, 15.0)
                   + min(quality["body_ratio"] * 10.0, 8.0)
                   + min(quality["range"] / atr * 5.0, 7.0))
    # _valid_plan in common filter computes structural stop; pass dummy stop (ignored)
    dummy_stop = entry - atr if direction == "LONG" else entry + atr
    plan = _raw_candidate(direction, entry, dummy_stop, atr, "volatility_breakout", strength, entry_reference=_entry_reference(data))
    if plan:
        plan["reasons"] = [
            f"1H 20-candle close breakout after volatility compression (bandwidth={prior_width:.4f})",
            f"Relative volume={volume_ratio:.2f}x median of prior 20 bars",
            f"Breakout candle body={quality['body_ratio']:.2f}; close-location={quality['close_location']:.2f}; range={quality['range'] / atr:.2f} ATR",
        ]
        plan["breakout_metrics"] = {"compression_bandwidth": round(prior_width, 6),
                                    "relative_volume": round(volume_ratio, 3),
                                    "candle_body_ratio": round(quality["body_ratio"], 3),
                                    "candle_range_atr": round(quality["range"] / atr, 3),
                                    "breakout_distance_atr": round(breakout_distance, 3),
                                    "acceptance": breakout_evidence, "volatility_regime": volatility_evidence}
    if plan:
        _attach_strategy_specialist_evidence(plan, specialist_evidence)
    return plan

