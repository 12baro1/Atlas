"""Independent orderflow_momentum setup generator."""

def _absorption_proxy(flow, candle, atr):
    """Infer passive absorption from aggressive trade delta plus stalled price.

    This is a snapshot proxy, not proof of hidden liquidity or queue replenishment.
    """
    from strategy_lab import _value
    if not isinstance(flow, dict) or not atr or atr <= 0:
        return None
    try:
        delta = float(flow.get("trade_delta") or 0.0)
        imbalance = float(flow.get("imbalance") or 0.0)
        opened = _value(candle, "open")
        close = _value(candle, "close")
        trade_count = int(flow.get("trade_count") or 0)
    except (TypeError, ValueError, OverflowError):
        return None
    if None in (opened, close) or trade_count < 20:
        return None
    price_progress = (close - opened) / atr
    if delta >= 0.18 and abs(price_progress) <= 0.15 and imbalance <= -0.10:
        return "BUYER_FLOW_ABSORBED"
    if delta <= -0.18 and abs(price_progress) <= 0.15 and imbalance >= 0.10:
        return "SELLER_FLOW_ABSORBED"
    return None


def generate(data):
    from strategy_lab import _atr, _ORDERBOOK_ENGINE, _value, _candle_quality, _current_price, _valid_plan, _entry_reference, _structure_candle_sets, displacement, cumulative_volume_delta, build_footprint, liquidity_walls, build_orderflow_evidence
    book = data.get("orderbook")
    candles = data.get("15m") or []
    atr = _atr(candles)
    now_ms = int(data.get("snapshot_timestamp_ms") or 0)
    book_ms = int(data.get("orderbook_timestamp_ms") or 0)
    trades_ms = int(data.get("recent_trades_timestamp_ms") or 0)
    if not isinstance(book, dict) or atr is None or not candles or not now_ms or not book_ms or not trades_ms:
        return None
    if not (0 <= now_ms - book_ms <= 15_000 and 0 <= now_ms - trades_ms <= 30_000):
        return None

    # Reuse Atlas's depth-normalized, notional-weighted order-book engine.
    # It rejects crossed/stale books and stale trades, and computes spread.
    flow = _ORDERBOOK_ENGINE.analyze(
        book,
        direction="NONE",
        now_ms=now_ms,
        trades=data.get("recent_trades"),
    )
    if not flow.get("active") or not flow.get("trade_flow_active"):
        return None
    imbalance = float(flow.get("imbalance") or 0.0)
    trade_delta = float(flow.get("trade_delta") or 0.0)
    spread_pct = float(flow.get("spread_pct") or 0.0)
    if spread_pct > _ORDERBOOK_ENGINE.MARKET_MAX_SPREAD_PCT:
        return None

    last = candles[-1]
    close, opened = _value(last, "close"), _value(last, "open")
    quality = _candle_quality(last)
    entry = _current_price(data)
    if close is None or opened is None or entry is None or quality is None:
        return None
    if int(flow.get("trade_count") or 0) < 20:
        return None
    absorption = _absorption_proxy(flow, last, atr)
    # CVD is a strategy input, not just a report metric. When a timestamped
    # WebSocket history exists, contradictory cumulative aggressor flow blocks
    # continuation entries; unavailable history is reported, never fabricated.
    cvd_evidence = cumulative_volume_delta(data.get("trade_flow_history") or [])
    orderflow_evidence = build_orderflow_evidence(
        data.get("recent_trades") or [], book, candles,
        data.get("liquidation_events") or [],
    )
    cvd_direction = cvd_evidence.get("direction") if cvd_evidence.get("state") == "AVAILABLE" else None
    direction = None
    if absorption == "BUYER_FLOW_ABSORBED":
        direction = "SHORT"
        stop = entry + 1.5 * atr
    elif absorption == "SELLER_FLOW_ABSORBED":
        direction = "LONG"
        stop = entry - 1.5 * atr
    elif (imbalance >= 0.18 and trade_delta >= 0.12 and close > opened and entry >= opened
          and quality["body_ratio"] >= 0.30 and quality["close_location"] >= 0.65
          and cvd_direction != "SELL_DOMINANT"):
        direction = "LONG"
        stop = entry - 1.5 * atr
    elif (imbalance <= -0.18 and trade_delta <= -0.12 and close < opened and entry <= opened
          and quality["body_ratio"] >= 0.30 and quality["close_location"] <= 0.35
          and cvd_direction != "BUY_DOMINANT"):
        direction = "SHORT"
        stop = entry + 1.5 * atr
    else:
        return None

    strength = min(92.0, 65.0 + min(abs(imbalance) * 35.0, 15.0) + min(abs(trade_delta) * 25.0, 10.0))
    if absorption:
        strength = min(94.0, strength + 2.0)
    plan = _valid_plan(direction, entry, stop, atr, candles, "orderflow_momentum", strength, entry_reference=_entry_reference(data), structure_candles=_structure_candle_sets(data))
    if plan:
        plan["reasons"] = [
            f"Depth-weighted order-book notional imbalance={imbalance:+.2f}",
            f"Recent taker notional delta={trade_delta:+.2f} across {int(flow.get('trade_count') or 0)} trades",
            f"Spread={spread_pct:.4f}%; bid/ask depth notional={flow.get('bid_notional')}/{flow.get('ask_notional')}",
            f"15m candle body={quality['body_ratio']:.2f}; close-location={quality['close_location']:.2f}",
        ]
        plan["data_quality"] = "ABSORPTION_PROXY" if absorption else "FRESH_BOOK_AND_NOTIONAL_TRADE_FLOW"
        if absorption:
            plan["reasons"].append(f"Absorption proxy: {absorption}; passive absorption is inferred, not directly observed")
        plan["orderflow_metrics"] = {
            "cvd": cvd_evidence,
            "footprint": orderflow_evidence.get("footprint"),
            "liquidity_walls": orderflow_evidence.get("liquidity_walls"),
            "recent_trade_cvd": orderflow_evidence.get("cvd"),
            "exchange_liquidations": orderflow_evidence.get("liquidations"),
            "bid_notional": flow.get("bid_notional"),
            "ask_notional": flow.get("ask_notional"),
            "trade_delta": trade_delta,
            "spread_pct": spread_pct,
            "trade_count": flow.get("trade_count"),
            "candle_body_ratio": round(quality["body_ratio"], 3),
            "candle_close_location": round(quality["close_location"], 3),
            "absorption_proxy": absorption,
            "displacement": displacement(candles, atr),
        }
    return plan
