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
    from strategy_lab import (
        _atr, _ORDERBOOK_ENGINE, _value, _candle_quality, _current_price,
        _valid_plan, _entry_reference, _structure_candle_sets, displacement,
        cumulative_volume_delta, build_orderflow_evidence,
    )
    from strategies.orderflow.analytics import (
        footprint_directional_evidence, opposing_liquidity_wall, liquidation_pressure,
    )

    shared_evidence = data.get("shared_market_evidence") or {}
    shared_sources = shared_evidence.get("sources") or {}
    book_source = shared_sources.get("orderbook") or {}
    trade_source = shared_sources.get("trades") or {}
    # When present, shared per-feed freshness is authoritative. Direct-call
    # fixtures without the shared contract retain the existing timestamp checks.
    if shared_sources and (
        book_source.get("state") != "FRESH" or trade_source.get("state") != "FRESH"
    ):
        return None
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

    # Depth-normalized order-book imbalance and actual recent taker flow.
    flow = _ORDERBOOK_ENGINE.analyze(
        book, direction="NONE", now_ms=now_ms, trades=data.get("recent_trades"),
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
    trade_count = int(flow.get("trade_count") or 0)
    if trade_count < 20:
        return None

    trades = data.get("recent_trades") or []
    liquidation_events = data.get("liquidation_events") or []
    absorption = _absorption_proxy(flow, last, atr)
    shared_analytics = data.get("shared_market_evidence") or {}
    if shared_analytics:
        shared_cvd = shared_analytics.get("cvd") or {}
        cvd_evidence = (
            shared_cvd if shared_cvd.get("state") == "FRESH"
            else {"state": "UNAVAILABLE", "reason": "SHARED_CVD_NOT_FRESH"}
        )
    else:
        cvd_evidence = cumulative_volume_delta(data.get("trade_flow_history") or [])
    evidence = build_orderflow_evidence(trades, book, candles, liquidation_events)
    footprint = shared_analytics.get("footprint") or evidence.get("footprint") or {}
    cvd_direction = cvd_evidence.get("direction") if cvd_evidence.get("state") in {"AVAILABLE", "FRESH"} else None

    # Footprint must confirm the aggressive flow behind the setup. For an
    # absorption reversal, it confirms the absorbed aggressor rather than the
    # eventual reversal direction.
    aggressor_direction = "LONG" if trade_delta > 0 else "SHORT" if trade_delta < 0 else None
    footprint_confirmation = (
        footprint_directional_evidence(footprint, aggressor_direction)
        if aggressor_direction else {"state": "UNAVAILABLE", "confirmed": False}
    )
    if not footprint_confirmation.get("confirmed"):
        return None

    liquidation = liquidation_pressure(liquidation_events, trades)
    direction = None
    setup_type = None
    if (liquidation.get("confirmed") and liquidation.get("direction") == "LONG"
            and close > opened and imbalance >= 0.10 and trade_delta >= 0.05
            and quality["close_location"] >= 0.55):
        direction, setup_type = "LONG", "LIQUIDATION_EXHAUSTION_REVERSAL"
    elif (liquidation.get("confirmed") and liquidation.get("direction") == "SHORT"
            and close < opened and imbalance <= -0.10 and trade_delta <= -0.05
            and quality["close_location"] <= 0.45):
        direction, setup_type = "SHORT", "LIQUIDATION_EXHAUSTION_REVERSAL"
    elif absorption == "BUYER_FLOW_ABSORBED":
        direction, setup_type = "SHORT", "ABSORPTION_REVERSAL"
    elif absorption == "SELLER_FLOW_ABSORBED":
        direction, setup_type = "LONG", "ABSORPTION_REVERSAL"
    elif (imbalance >= 0.18 and trade_delta >= 0.12 and close > opened and entry >= opened
          and quality["body_ratio"] >= 0.30 and quality["close_location"] >= 0.65
          and cvd_direction != "SELL_DOMINANT"):
        direction, setup_type = "LONG", "ORDERFLOW_CONTINUATION"
    elif (imbalance <= -0.18 and trade_delta <= -0.12 and close < opened and entry <= opened
          and quality["body_ratio"] >= 0.30 and quality["close_location"] <= 0.35
          and cvd_direction != "BUY_DOMINANT"):
        direction, setup_type = "SHORT", "ORDERFLOW_CONTINUATION"
    else:
        return None

    # A nearby oversized opposing wall blocks a marketable continuation;
    # displayed depth is treated as a risk boundary, never as guaranteed support.
    wall = opposing_liquidity_wall(book, direction, entry, atr)
    if wall.get("blocking"):
        return None

    strength = min(92.0, 65.0 + min(abs(imbalance) * 35.0, 15.0)
                   + min(abs(trade_delta) * 25.0, 10.0))
    if absorption or liquidation.get("confirmed"):
        strength = min(94.0, strength + 2.0)
    stop = entry + 1.5 * atr if direction == "SHORT" else entry - 1.5 * atr
    plan = _valid_plan(
        direction, entry, stop, atr, candles, "orderflow_momentum", strength,
        entry_reference=_entry_reference(data), structure_candles=_structure_candle_sets(data),
    )
    if plan:
        reasons = [
            f"Orderflow setup={setup_type}",
            f"Depth-weighted order-book notional imbalance={imbalance:+.2f}",
            f"Recent taker notional delta={trade_delta:+.2f} across {trade_count} trades",
            f"Footprint buy/sell imbalance={footprint_confirmation.get('imbalance'):+.3f} across {footprint_confirmation.get('price_levels')} price levels",
            f"Spread={spread_pct:.4f}%; bid/ask depth notional={flow.get('bid_notional')}/{flow.get('ask_notional')}",
            f"15m candle body={quality['body_ratio']:.2f}; close-location={quality['close_location']:.2f}",
        ]
        if absorption:
            reasons.append(
                f"Absorption proxy: {absorption}; passive absorption is inferred, not directly observed"
            )
        if liquidation.get("confirmed"):
            reasons.append(
                f"Exchange liquidation exhaustion: {liquidation.get('direction')} "
                f"dominant_share={liquidation.get('dominant_share'):.2f}, "
                f"trade_notional_ratio={liquidation.get('trade_notional_ratio'):.2f}"
            )
        if wall.get("state") == "AVAILABLE":
            reasons.append(
                f"Nearest opposing displayed wall={wall.get('price')} "
                f"({wall.get('distance_atr')} ATR, {wall.get('size_multiple')}x median)"
            )
        plan["reasons"] = reasons
        plan["data_quality"] = "FRESH_BOOK_TRADES_FOOTPRINT"
        plan["orderflow_metrics"] = {
            "setup_type": setup_type,
            "cvd": cvd_evidence,
            "footprint": footprint,
            "footprint_confirmation": footprint_confirmation,
            "liquidity_walls": shared_analytics.get("liquidity_walls") or evidence.get("liquidity_walls"),
            "opposing_wall_risk": wall,
            "recent_trade_cvd": evidence.get("cvd"),
            "exchange_liquidations": evidence.get("liquidations"),
            "liquidation_pressure": liquidation,
            "bid_notional": flow.get("bid_notional"),
            "ask_notional": flow.get("ask_notional"),
            "trade_delta": trade_delta,
            "spread_pct": spread_pct,
            "trade_count": trade_count,
            "candle_body_ratio": round(quality["body_ratio"], 3),
            "candle_close_location": round(quality["close_location"], 3),
            "absorption_proxy": absorption,
            "displacement": displacement(candles, atr),
        }
    return plan
