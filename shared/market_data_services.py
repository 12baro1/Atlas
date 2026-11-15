"""Strategy-neutral evidence derived from one timestamped market-data snapshot.

The service never invents missing feeds. Each source has an independent state,
timestamp, age and provenance so consumers can distinguish unavailable,
stale and usable evidence.
"""
from __future__ import annotations

import math


def _number(value):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _freshness(timestamp_ms, now_ms, max_age_ms):
    try:
        stamp = int(timestamp_ms)
        now = int(now_ms)
    except (TypeError, ValueError, OverflowError):
        return {"state": "UNAVAILABLE", "age_ms": None}
    age = now - stamp
    if age < 0:
        return {"state": "INVALID_FUTURE_TIMESTAMP", "age_ms": age}
    return {"state": "FRESH" if age <= max_age_ms else "STALE", "age_ms": age}


def _trade_evidence(trades):
    buy = sell = 0.0
    count = 0
    for trade in trades or []:
        if not isinstance(trade, dict):
            continue
        price = _number(trade.get("price"))
        size = _number(trade.get("size", trade.get("amount")))
        side = str(trade.get("side") or "").upper()
        if price is None or size is None or price <= 0 or size <= 0 or side not in {"BUY", "SELL"}:
            continue
        if side == "BUY":
            buy += price * size
        else:
            sell += price * size
        count += 1
    total = buy + sell
    if count == 0 or total <= 0:
        return {"state": "UNAVAILABLE", "trade_count": 0}
    return {
        "state": "AVAILABLE",
        "trade_count": count,
        "buy_notional": buy,
        "sell_notional": sell,
        "net_delta": buy - sell,
        "delta_ratio": (buy - sell) / total,
        "buy_ratio": buy / total,
    }


def _orderbook_evidence(book):
    if not isinstance(book, dict):
        return {"state": "UNAVAILABLE"}
    sides = {}
    for name in ("bids", "asks"):
        levels = []
        for row in book.get(name) or []:
            try:
                price, size = _number(row[0]), _number(row[1])
            except (TypeError, IndexError):
                continue
            if price is not None and size is not None and price > 0 and size > 0:
                levels.append((price, size))
        sides[name] = levels
    bids, asks = sides["bids"], sides["asks"]
    if not bids or not asks:
        return {"state": "UNAVAILABLE", "bid_levels": len(bids), "ask_levels": len(asks)}
    bid_notional = sum(price * size for price, size in bids)
    ask_notional = sum(price * size for price, size in asks)
    total = bid_notional + ask_notional
    best_bid, best_ask = max(price for price, _ in bids), min(price for price, _ in asks)
    if total <= 0 or best_ask <= best_bid:
        return {"state": "INVALID_DATA"}
    midpoint = (best_bid + best_ask) / 2
    return {
        "state": "AVAILABLE",
        "bid_levels": len(bids),
        "ask_levels": len(asks),
        "bid_notional": bid_notional,
        "ask_notional": ask_notional,
        "imbalance": (bid_notional - ask_notional) / total,
        "spread_pct": (best_ask - best_bid) / midpoint * 100,
        "best_bid": best_bid,
        "best_ask": best_ask,
    }


def _liquidation_evidence(events, now_ms):
    long_notional = short_notional = 0.0
    accepted = 0
    for event in events or []:
        if not isinstance(event, dict):
            continue
        freshness = _freshness(event.get("timestamp_ms"), now_ms, 900_000)
        if freshness["state"] != "FRESH":
            continue
        notional = _number(event.get("notional"))
        side = str(event.get("side") or "").upper()
        if notional is None or notional <= 0 or side not in {"BUY", "SELL"}:
            continue
        # Bybit allLiquidation S is position side, not taker side:
        # BUY = a long position was liquidated; SELL = a short was liquidated.
        if side == "BUY":
            long_notional += notional
        else:
            short_notional += notional
        accepted += 1
    total = long_notional + short_notional
    if not accepted or total <= 0:
        return {"state": "UNAVAILABLE", "event_count": 0}
    return {
        "state": "AVAILABLE",
        "event_count": accepted,
        "long_liquidation_notional": long_notional,
        "short_liquidation_notional": short_notional,
        "long_share": long_notional / total,
        "short_share": short_notional / total,
    }


def _series_evidence(values, timestamps, now_ms, max_age_ms):
    if not values:
        return {"state": "UNAVAILABLE", "count": 0}
    if len(values) != len(timestamps):
        return {"state": "MISSING_TIMESTAMPS", "count": len(values)}
    parsed = []
    for value, stamp in zip(values, timestamps):
        number = _number(value)
        try:
            stamp = int(stamp)
        except (TypeError, ValueError, OverflowError):
            return {"state": "INVALID_DATA", "count": len(values)}
        if number is None:
            return {"state": "INVALID_DATA", "count": len(values)}
        parsed.append((stamp, number))
    parsed.sort(key=lambda item: item[0])
    freshness = _freshness(parsed[-1][0], now_ms, max_age_ms)
    result = {"state": freshness["state"], "count": len(parsed),
              "latest_timestamp_ms": parsed[-1][0], "age_ms": freshness["age_ms"],
              "latest": parsed[-1][1]}
    if len(parsed) >= 2 and parsed[-2][1] != 0:
        result["change_pct"] = round((parsed[-1][1] / parsed[-2][1] - 1.0) * 100, 6)
    return result


def _footprint_evidence(trades):
    levels = {}
    for trade in trades or []:
        if not isinstance(trade, dict):
            continue
        price = _number(trade.get("price"))
        size = _number(trade.get("size", trade.get("amount")))
        side = str(trade.get("side") or "").upper()
        if price is None or size is None or price <= 0 or size <= 0 or side not in {"BUY", "SELL"}:
            continue
        key = format(price, ".12g")
        row = levels.setdefault(key, {"buy_notional": 0.0, "sell_notional": 0.0, "trades": 0})
        row["buy_notional" if side == "BUY" else "sell_notional"] += price * size
        row["trades"] += 1
    return {"state": "AVAILABLE", "levels": levels} if levels else {"state": "UNAVAILABLE"}


def _liquidity_wall_evidence(book, top_n=20):
    if not isinstance(book, dict):
        return {"state": "UNAVAILABLE"}
    result = {}
    for side in ("bids", "asks"):
        levels = []
        for row in (book.get(side) or [])[:max(1, int(top_n))]:
            try:
                price, size = _number(row[0]), _number(row[1])
            except (TypeError, IndexError):
                continue
            if price is not None and size is not None and price > 0 and size > 0:
                levels.append({"price": price, "notional": price * size})
        result[side] = sorted(levels, key=lambda item: item["notional"], reverse=True)
    return {
        "state": "AVAILABLE" if result["bids"] or result["asks"] else "UNAVAILABLE",
        **result,
        "disclaimer": "Displayed resting orders may be cancelled; not proof of support/resistance",
    }


def _cvd_evidence(trade_flow_history):
    from shared.microstructure_services import cumulative_volume_delta
    return cumulative_volume_delta(trade_flow_history or [])


def build_shared_market_evidence(data):
    """Build immutable-style, strategy-neutral evidence from raw market data."""
    data = data if isinstance(data, dict) else {}
    now_ms = data.get("snapshot_timestamp_ms")
    try:
        now_ms = int(now_ms)
    except (TypeError, ValueError, OverflowError):
        now_ms = 0

    book = _orderbook_evidence(data.get("orderbook"))
    book_freshness = _freshness(data.get("orderbook_timestamp_ms"), now_ms, 15_000)
    if book["state"] == "AVAILABLE":
        book["freshness"] = book_freshness
        if book_freshness["state"] != "FRESH":
            book["state"] = book_freshness["state"]

    trades = _trade_evidence(data.get("recent_trades"))
    trade_freshness = _freshness(data.get("recent_trades_timestamp_ms"), now_ms, 30_000)
    if trades["state"] == "AVAILABLE":
        trades["freshness"] = trade_freshness
        if trade_freshness["state"] != "FRESH":
            trades["state"] = trade_freshness["state"]

    oi = _series_evidence(data.get("open_interest") or [],
                          data.get("open_interest_timestamps_ms") or [], now_ms, 2 * 60 * 60 * 1000)
    funding = _series_evidence(data.get("funding_rate") or [],
                               data.get("funding_rate_timestamps_ms") or [], now_ms, 8 * 60 * 60 * 1000)
    liquidations = _liquidation_evidence(data.get("liquidation_events") or [], now_ms)
    footprint = _footprint_evidence(data.get("recent_trades") or [])
    liquidity_walls = _liquidity_wall_evidence(data.get("orderbook"))
    cvd = _cvd_evidence(data.get("trade_flow_history") or [])

    candle_counts = {
        timeframe: len(data.get(timeframe) or [])
        for timeframe in ("15m", "1h", "4h", "1d", "1w")
    }
    return {
        "schema_version": 1,
        "snapshot_timestamp_ms": now_ms or None,
        "sources": {
            "ohlcv": {"state": "AVAILABLE" if any(candle_counts.values()) else "UNAVAILABLE",
                      "candle_counts": candle_counts},
            "orderbook": {"state": book.get("state", "UNAVAILABLE"),
                          "source": (data.get("data_provenance") or {}).get("orderbook", "UNKNOWN"),
                          "timestamp_ms": data.get("orderbook_timestamp_ms")},
            "trades": {"state": trades.get("state", "UNAVAILABLE"),
                       "source": (data.get("data_provenance") or {}).get("recent_trades", "UNKNOWN"),
                       "timestamp_ms": data.get("recent_trades_timestamp_ms")},
            "liquidations": {"state": liquidations["state"],
                             "source": (data.get("data_provenance") or {}).get("liquidations", "UNKNOWN")},
            "open_interest": {"state": oi["state"], "source": (data.get("data_provenance") or {}).get("open_interest", "UNKNOWN")},
            "funding": {"state": funding["state"], "source": (data.get("data_provenance") or {}).get("funding_rate", "UNKNOWN")},
        },
        "orderbook": book,
        "trades": trades,
        "cvd": cvd,
        "footprint": footprint,
        "liquidity_walls": liquidity_walls,
        "liquidations": liquidations,
        "open_interest": oi,
        "funding": funding,
        "correlation_universe": {
            key: len(value or []) for key, value in (data.get("correlation_universe") or {}).items()
        },
        "sector_peer_universe": {
            key: len((value or {}).get("4h") or []) for key, value in (data.get("sector_peer_universe") or {}).items()
        },
    }
