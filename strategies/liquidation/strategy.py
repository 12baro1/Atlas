import math


"""Independent liquidation_cascade setup generator."""

def generate(data):
    from strategy_lab import _atr, _value, _candle_quality, _relative_volume, _trade_flow, _current_price, _valid_plan, _entry_reference, _structure_candle_sets, liquidation_events
    """Detect a liquidation-like deleveraging impulse; OI is a proxy, not event data."""
    candles = data.get("1h") or []
    oi_raw = data.get("open_interest") or []
    oi_times_raw = data.get("open_interest_timestamps_ms") or []
    atr = _atr(candles)
    if len(candles) < 21 or atr is None:
        return None
    # OI gözlemleri yalnızca zaman damgasıyla hizalı çiftlerden kurulur.
    # Sonradan eklenen zaman damgasız anlık snapshot tarihsel seriye karışmaz;
    # böylece değer/timestamp dizin kayması değişimi bozamaz.
    aligned = []
    for stamp, value in zip(oi_times_raw, oi_raw):
        try:
            stamp = int(stamp)
            value = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(value):
            aligned.append((stamp, value))
    aligned.sort(key=lambda pair: pair[0])
    # Zaman damgası olmayan trailing snapshot ayrı tutulur (tarihsel seriye girmez).
    oi_snapshot_value = oi_raw[len(oi_times_raw)] if len(oi_raw) > len(oi_times_raw) else None
    if len(aligned) < 2:
        return None
    previous_ms, previous_oi = aligned[-2]
    current_ms, current_oi = aligned[-1]
    if previous_oi <= 0 or not math.isfinite(previous_oi) or not math.isfinite(current_oi):
        return None
    now_ms = int(data.get("snapshot_timestamp_ms") or 0)
    if not now_ms:
        return None
    if not (0 <= now_ms - current_ms <= 2 * 60 * 60 * 1000):
        return None
    if not (0 < current_ms - previous_ms <= 3 * 60 * 60 * 1000):
        return None
    oi_change = (current_oi - previous_oi) / previous_oi
    last = candles[-1]
    close, opened = _value(last, "close"), _value(last, "open")
    quality = _candle_quality(last)
    relative_volume = _relative_volume(candles, 20)
    buy_ratio, _ = _trade_flow(data)
    entry = _current_price(data)
    if close is None or opened is None or entry is None or quality is None or relative_volume is None:
        return None
    impulse = abs(close - opened) / atr
    direction = None
    funding_values = data.get("funding_rate") or []
    try:
        funding = float(funding_values[-1]) if funding_values else 0.0
    except (TypeError, ValueError, OverflowError):
        funding = 0.0
    if not math.isfinite(funding):
        return None
    # Crowded-side funding is used as a directional confirmation, not as a
    # standalone trigger: positive funding supports long-liquidation shorts;
    # negative funding supports short-squeeze longs.
    if (oi_change <= -0.015 and close > opened and entry > opened and impulse >= 1.0
            and quality["direction"] == "BULLISH" and quality["close_location"] >= 0.70
            and relative_volume >= 1.25 and buy_ratio is not None and buy_ratio >= 0.56
            and funding <= 0.0003):
        direction = "LONG"
        stop = entry - 1.5 * atr
    elif (oi_change <= -0.015 and close < opened and entry < opened and impulse >= 1.0
            and quality["direction"] == "BEARISH" and quality["close_location"] <= 0.30
            and relative_volume >= 1.25 and buy_ratio is not None and buy_ratio <= 0.44
            and funding >= -0.0003):
        direction = "SHORT"
        stop = entry + 1.5 * atr
    else:
        return None
    strength = min(92.0, 65.0 + min(abs(oi_change) * 400.0, 15.0) + min(impulse * 5.0, 10.0))
    plan = _valid_plan(direction, entry, stop, atr, candles, "liquidation_cascade", strength, entry_reference=_entry_reference(data), structure_candles=_structure_candle_sets(data))
    if plan:
        plan["reasons"] = [
            f"Open interest contraction={oi_change * 100:.2f}% over timestamped observations",
            f"1H impulse={impulse:.2f} ATR; relative volume={relative_volume:.2f}x",
            f"Taker buy-notional ratio={buy_ratio:.2f}; funding={funding:.5f}",
            f"Impulse candle close-location={quality['close_location']:.2f}",
            "Liquidation-side interpretation is an OI/flow proxy, not exchange liquidation-event data",
        ]
        plan["data_quality"] = "OI_CONTRACTION_PROXY_NOT_EXCHANGE_LIQUIDATION_FEED"
        event_evidence = liquidation_events(data.get("liquidation_events") or [], now_ms=now_ms)
        plan["liquidation_metrics"] = {"exchange_events": event_evidence,
                                      "event_class": "SHORT_SQUEEZE_PROXY" if direction == "SHORT" else "LONG_SQUEEZE_PROXY",
                                      "oi_change_pct": round(oi_change * 100, 3),
                                      "oi_history_samples": len(aligned),
                                      "oi_snapshot_value": oi_snapshot_value,
                                      "impulse_atr": round(impulse, 3),
                                      "relative_volume": round(relative_volume, 3),
                                      "taker_buy_notional_ratio": round(buy_ratio, 3),
                                      "funding_rate": funding}
    return plan
