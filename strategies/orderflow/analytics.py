"""Order-flow analytics over observed exchange events; never synthesize feeds."""
from __future__ import annotations

import math
from collections import defaultdict

from shared.analysis_context import cached_analysis


@cached_analysis
def _number(value):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


@cached_analysis
def build_cvd(trades):
    """Build timestamp-ordered cumulative taker delta from actual public trades."""
    rows = []
    for trade in trades or []:
        if not isinstance(trade, dict):
            continue
        price, size = _number(trade.get("price")), _number(trade.get("size", trade.get("amount")))
        stamp = trade.get("timestamp_ms", trade.get("timestamp"))
        side = str(trade.get("side") or "").upper()
        try:
            stamp = int(stamp)
        except (TypeError, ValueError, OverflowError):
            continue
        if price is None or size is None or price <= 0 or size <= 0 or side not in {"BUY", "SELL"}:
            continue
        rows.append((stamp, price * size, side))
    rows.sort(key=lambda item: item[0])
    cumulative, series = 0.0, []
    for stamp, notional, side in rows:
        delta = notional if side == "BUY" else -notional
        cumulative += delta
        series.append({"timestamp_ms": stamp, "delta_notional": delta, "cvd": cumulative})
    return {"state": "AVAILABLE", "trade_count": len(series), "net_delta": cumulative,
            "direction": "BUY_DOMINANT" if cumulative > 0 else "SELL_DOMINANT" if cumulative < 0 else "BALANCED",
            "series": series} if series else {"state": "UNAVAILABLE", "reason": "NO_VALID_AGGRESSOR_TRADES"}


@cached_analysis
def build_footprint(trades, price_step=0.0):
    """Aggregate executed buy/sell notional by observed price level."""
    step = _number(price_step) or 0.0
    levels = defaultdict(lambda: {"buy_notional": 0.0, "sell_notional": 0.0, "trades": 0})
    for trade in trades or []:
        if not isinstance(trade, dict):
            continue
        price, size = _number(trade.get("price")), _number(trade.get("size", trade.get("amount")))
        side = str(trade.get("side") or "").upper()
        if price is None or size is None or price <= 0 or size <= 0 or side not in {"BUY", "SELL"}:
            continue
        level = round(price / step) * step if step > 0 else price
        key = format(level, ".12g")
        field = "buy_notional" if side == "BUY" else "sell_notional"
        levels[key][field] += price * size
        levels[key]["trades"] += 1
    return {"state": "AVAILABLE", "levels": dict(levels)} if levels else {"state": "UNAVAILABLE"}


@cached_analysis
def absorption_evidence(trades, candles, min_imbalance=0.20):
    """Conservative absorption proxy: aggressive delta opposed by candle close.

    This is explicitly a proxy; passive fills cannot be proven from public trades.
    """
    cvd = build_cvd(trades)
    if cvd.get("state") != "AVAILABLE" or not candles:
        return {"state": "UNAVAILABLE"}
    buy = sum(x["delta_notional"] for x in cvd["series"] if x["delta_notional"] > 0)
    sell = -sum(x["delta_notional"] for x in cvd["series"] if x["delta_notional"] < 0)
    total = buy + sell
    if total <= 0:
        return {"state": "UNAVAILABLE"}
    candle = candles[-1]
    try:
        opened, close = float(candle.open), float(candle.close)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return {"state": "UNAVAILABLE"}
    imbalance = (buy - sell) / total
    label = "BUYER_FLOW_ABSORBED_PROXY" if imbalance >= min_imbalance and close < opened else \
            "SELLER_FLOW_ABSORBED_PROXY" if imbalance <= -min_imbalance and close > opened else "NONE"
    return {"state": "AVAILABLE", "classification": label, "buy_sell_imbalance": round(imbalance, 4),
            "disclaimer": "Public trade/candle inference only; passive absorption is not directly observable"}


@cached_analysis
def liquidity_walls(orderbook, top_n=20):
    """Rank displayed L2 depth concentrations; walls are not executed liquidity."""
    if not isinstance(orderbook, dict):
        return {"state": "UNAVAILABLE"}
    result = {}
    for side in ("bids", "asks"):
        levels = []
        for row in (orderbook.get(side) or [])[:max(1, int(top_n))]:
            try:
                price, size = float(row[0]), float(row[1])
            except (TypeError, ValueError, IndexError, OverflowError):
                continue
            if math.isfinite(price) and math.isfinite(size) and price > 0 and size > 0:
                levels.append({"price": price, "notional": price * size})
        result[side] = sorted(levels, key=lambda x: x["notional"], reverse=True)
    return {"state": "AVAILABLE" if result["bids"] or result["asks"] else "UNAVAILABLE", **result,
            "disclaimer": "Displayed resting orders may be cancelled; not proof of support/resistance"}


@cached_analysis
def build_orderflow_evidence(trades, orderbook, candles=(), liquidation_events=()):
    return {"cvd": build_cvd(trades), "footprint": build_footprint(trades),
            "absorption": absorption_evidence(trades, candles),
            "liquidity_walls": liquidity_walls(orderbook),
            "liquidations": {"state": "AVAILABLE", "events": list(liquidation_events)} if liquidation_events else
                           {"state": "UNAVAILABLE", "reason": "NO_EXCHANGE_LIQUIDATION_EVENTS"}}
