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


def footprint_directional_evidence(footprint, direction, min_imbalance=0.05):
    """Return whether executed footprint notional confirms the proposed direction."""
    if not isinstance(footprint, dict) or footprint.get("state") != "AVAILABLE":
        return {"state": "UNAVAILABLE", "confirmed": False}
    levels = footprint.get("levels") or {}
    buy = sum(_number(row.get("buy_notional")) or 0.0 for row in levels.values() if isinstance(row, dict))
    sell = sum(_number(row.get("sell_notional")) or 0.0 for row in levels.values() if isinstance(row, dict))
    total = buy + sell
    if total <= 0:
        return {"state": "UNAVAILABLE", "confirmed": False}
    imbalance = (buy - sell) / total
    aligned = imbalance >= min_imbalance if direction == "LONG" else imbalance <= -min_imbalance
    aligned_notional = 0.0
    aligned_levels = 0
    for row in levels.values():
        if not isinstance(row, dict):
            continue
        level_buy = _number(row.get("buy_notional")) or 0.0
        level_sell = _number(row.get("sell_notional")) or 0.0
        level_total = level_buy + level_sell
        if level_total <= 0:
            continue
        level_delta = (level_buy - level_sell) / level_total
        level_aligned = level_delta >= min_imbalance if direction == "LONG" else level_delta <= -min_imbalance
        if level_aligned:
            aligned_levels += 1
            aligned_notional += level_total
    aligned_share = aligned_notional / total
    confirmed = bool(aligned and aligned_levels >= 2 and aligned_share >= 0.45)
    return {"state": "AVAILABLE", "confirmed": confirmed, "imbalance": round(imbalance, 4),
            "buy_notional": buy, "sell_notional": sell, "price_levels": len(levels),
            "aligned_levels": aligned_levels, "aligned_notional_share": round(aligned_share, 4)}


def opposing_liquidity_wall(orderbook, direction, entry, atr, proximity_atr=0.20, size_multiple=2.5):
    """Detect a nearby unusually large opposing displayed wall; never treat it as executed liquidity."""
    entry, atr = _number(entry), _number(atr)
    if not isinstance(orderbook, dict) or entry is None or atr is None or atr <= 0:
        return {"state": "UNAVAILABLE", "blocking": False}
    side = "asks" if direction == "LONG" else "bids"
    rows = []
    for row in orderbook.get(side) or []:
        try:
            price, size = _number(row[0]), _number(row[1])
        except (TypeError, IndexError):
            continue
        if price is None or size is None or price <= 0 or size <= 0:
            continue
        notional = price * size
        if (direction == "LONG" and price > entry) or (direction == "SHORT" and price < entry):
            rows.append((price, notional))
    if len(rows) < 3:
        return {"state": "UNAVAILABLE", "blocking": False}
    notionals = sorted(item[1] for item in rows)
    middle = len(notionals) // 2
    baseline = notionals[middle] if len(notionals) % 2 else (notionals[middle - 1] + notionals[middle]) / 2
    if baseline <= 0:
        return {"state": "UNAVAILABLE", "blocking": False}
    nearest = min(rows, key=lambda item: abs(item[0] - entry))
    distance_atr = abs(nearest[0] - entry) / atr
    multiple = nearest[1] / baseline
    blocking = distance_atr <= proximity_atr and multiple >= size_multiple
    return {"state": "AVAILABLE", "blocking": bool(blocking), "side": side,
            "price": nearest[0], "notional": nearest[1], "median_notional": baseline,
            "size_multiple": round(multiple, 3), "distance_atr": round(distance_atr, 3),
            "disclaimer": "Displayed resting orders may be cancelled; this is a proximity risk, not guaranteed resistance/support"}


def liquidation_pressure(events, recent_trades, min_share=0.65, min_trade_notional_ratio=0.10):
    """Identify a material liquidation-side imbalance using actual recent exchange events."""
    buy_liq = sell_liq = 0.0
    valid = 0
    for event in events or []:
        if not isinstance(event, dict):
            continue
        side = str(event.get("order_side") or event.get("side") or "").upper()
        notional = _number(event.get("notional"))
        if side not in {"BUY", "SELL"} or notional is None or notional <= 0:
            continue
        if side == "BUY":
            buy_liq += notional
        else:
            sell_liq += notional
        valid += 1
    trade_notional = sum(
        (_number(item.get("price")) or 0.0) * (_number(item.get("size", item.get("amount"))) or 0.0)
        for item in recent_trades or [] if isinstance(item, dict)
    )
    total = buy_liq + sell_liq
    if not valid or total <= 0 or trade_notional <= 0:
        return {"state": "UNAVAILABLE", "direction": None, "confirmed": False}
    dominant_share = max(buy_liq, sell_liq) / total
    relative_size = total / trade_notional
    if dominant_share < min_share or relative_size < min_trade_notional_ratio:
        return {"state": "AVAILABLE", "direction": None, "confirmed": False,
                "dominant_share": round(dominant_share, 4), "trade_notional_ratio": round(relative_size, 4),
                "events": valid, "buy_liquidation_order_notional": buy_liq, "sell_liquidation_order_notional": sell_liq,
            "side_semantics": "GATE_LIQUIDATION_ORDER_SIDE_FADED_TO_CANDIDATE_DIRECTION"}
    # Gate public_liquidates.size is the liquidation ORDER side, not the
    # liquidated position side. A buy-to-close order liquidates shorts; fading
    # that exhausted short side yields LONG. A sell-to-close order liquidates
    # longs; fading them yields SHORT.
    direction = "LONG" if buy_liq > sell_liq else "SHORT"
    return {"state": "AVAILABLE", "direction": direction, "confirmed": True,
            "dominant_share": round(dominant_share, 4), "trade_notional_ratio": round(relative_size, 4),
            "events": valid, "buy_liquidation_notional": buy_liq, "sell_liquidation_notional": sell_liq}


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
    label = ("BUYER_FLOW_ABSORBED_PROXY" if imbalance >= min_imbalance and close < opened else
             "SELLER_FLOW_ABSORBED_PROXY" if imbalance <= -min_imbalance and close > opened else "NONE")
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
