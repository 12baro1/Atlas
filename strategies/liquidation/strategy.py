import math


"""Independent liquidation_cascade setup generator."""

def generate(data):
    from strategy_lab import _atr, _value, _candle_quality, _relative_volume, _trade_flow, _current_price, _raw_candidate, _entry_reference, liquidation_events
    """Detect a liquidation-like deleveraging impulse; OI is a proxy, not event data."""
    candles = data.get("1h") or []
    oi = data.get("open_interest") or []
    atr = _atr(candles)
    if len(candles) < 21 or len(oi) < 2 or atr is None:
        return None
    try:
        previous_oi, current_oi = float(oi[-2]), float(oi[-1])
    except (TypeError, ValueError, OverflowError):
        return None
    if previous_oi <= 0 or not math.isfinite(previous_oi) or not math.isfinite(current_oi):
        return None
    oi_times = data.get("open_interest_timestamps_ms") or []
    now_ms = int(data.get("snapshot_timestamp_ms") or 0)
    shared_evidence = data.get("shared_market_evidence") or {}
    shared_oi = shared_evidence.get("open_interest") or {}
    if shared_evidence and (
        shared_oi.get("state") != "FRESH" or int(shared_oi.get("count") or 0) < 2
    ):
        return None
    if len(oi_times) < 2 or not now_ms:
        return None
    try:
        previous_oi_ms, current_oi_ms = int(oi_times[-2]), int(oi_times[-1])
    except (TypeError, ValueError, OverflowError):
        return None
    if not (0 <= now_ms - current_oi_ms <= 2 * 60 * 60 * 1000):
        return None
    if not (0 < current_oi_ms - previous_oi_ms <= 3 * 60 * 60 * 1000):
        return None
    oi_change = (
        float(shared_oi["change_pct"]) / 100.0
        if shared_evidence and shared_oi.get("change_pct") is not None
        else (current_oi - previous_oi) / previous_oi
    )
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
    shared_funding = shared_evidence.get("funding") or {}
    try:
        if shared_evidence:
            funding = (
                float(shared_funding["latest"])
                if shared_funding.get("state") == "FRESH" and shared_funding.get("latest") is not None
                else 0.0
            )
        else:
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
    event_evidence = liquidation_events(data.get("liquidation_events") or [], now_ms=now_ms)
    event_direction = None
    event_alignment = "UNAVAILABLE"
    if event_evidence.get("state") == "AVAILABLE":
        long_liquidations = float(event_evidence.get("long_liquidation_notional") or 0.0)
        short_liquidations = float(event_evidence.get("short_liquidation_notional") or 0.0)
        if short_liquidations > long_liquidations:
            event_direction = "LONG"
        elif long_liquidations > short_liquidations:
            event_direction = "SHORT"
        if event_direction:
            event_alignment = "ALIGNED" if event_direction == direction else "OPPOSING"

    strength = min(92.0, 65.0 + min(abs(oi_change) * 400.0, 15.0) + min(impulse * 5.0, 10.0))
    if event_alignment == "ALIGNED":
        strength = min(95.0, strength + 3.0)
    elif event_alignment == "OPPOSING":
        strength = max(55.0, strength - 2.0)
    plan = _raw_candidate(direction, entry, stop, atr, "liquidation_cascade", strength, entry_reference=_entry_reference(data))
    if plan:
        plan["reasons"] = [
            f"Open interest contraction={oi_change * 100:.2f}% over timestamped observations",
            f"1H impulse={impulse:.2f} ATR; relative volume={relative_volume:.2f}x",
            f"Taker buy-notional ratio={buy_ratio:.2f}; funding={funding:.5f}",
            f"Impulse candle close-location={quality['close_location']:.2f}",
            "Liquidation-side interpretation is an OI/flow proxy, not exchange liquidation-event data",
        ]
        plan["data_quality"] = "OI_CONTRACTION_PROXY_NOT_EXCHANGE_LIQUIDATION_FEED"
        plan["liquidation_metrics"] = {"exchange_events": event_evidence,
                                      "event_direction": event_direction,
                                      "event_alignment": event_alignment,
                                      "event_class": "SHORT_SQUEEZE_PROXY" if direction == "SHORT" else "LONG_SQUEEZE_PROXY",
                                      "oi_change_pct": round(oi_change * 100, 3),
                                      "impulse_atr": round(impulse, 3),
                                      "relative_volume": round(relative_volume, 3),
                                      "taker_buy_notional_ratio": round(buy_ratio, 3),
                                      "funding_rate": funding}
    return plan
