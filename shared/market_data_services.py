"""Shared market-data usage evidence.

Bu servis yalnızca ortak piyasa kanıtı üretir: her veri türünün kaynağı
(REST / WEBSOCKET / REST_SNAPSHOT_ONLY / UNAVAILABLE), durumu, yaşı ve örnek
sayısı. Strateji kararı üretmez; hiçbir stratejinin bağımsız karar mantığını
değiştirmez ve kullanılmayan veriyi kullanılmış gibi göstermez.

Kaynak etiketleri data_engine tarafından gerçekten kullanılan veriye göre
yazılır: bağlantı kurulmuş olması tek başına "WEBSOCKET" anlamına gelmez.
"""
from __future__ import annotations

import math
import time

ORDERBOOK_FRESH_MAX_MS = 15_000
TRADES_FRESH_MAX_MS = 30_000
OI_FRESH_MAX_MS = 2 * 60 * 60 * 1000
MIN_TIMESTAMPED_OI_OBSERVATIONS = 2


def _finite_int(value):
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(float(number)) else None


def _finite_float(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _age_ms(timestamp_ms, now_ms):
    """Non-negative age in ms, or None for missing/future timestamps."""
    stamp = _finite_int(timestamp_ms)
    reference = _finite_int(now_ms)
    if stamp is None or reference is None:
        return None
    delta = reference - stamp
    if delta < 0:
        return None
    return delta


def _freshness(age, max_age_ms):
    if age is None:
        return "UNKNOWN"
    if age <= max_age_ms:
        return "FRESH"
    return "STALE"


def _source(data, key, fallback="UNAVAILABLE"):
    value = str(data.get(key) or "").upper()
    return value if value else fallback


def market_feed_evidence(data, now_ms=None):
    """Per-feed availability, source separation, freshness and sample counts.

    Ortak kanıt: stratejiler bunu okuyabilir ama karar mantığı bu serviste
    değildir. Eksik veri nedenleri açıkça raporlanır; bilinmeyen değerler
    bilinmeyen olarak kalır.
    """
    data = data if isinstance(data, dict) else {}
    snapshot_ms = _finite_int(now_ms)
    if snapshot_ms is None:
        snapshot_ms = _finite_int(data.get("snapshot_timestamp_ms"))
    if snapshot_ms is None:
        snapshot_ms = int(time.time() * 1000)

    feeds = {}

    # --- Orderbook ---------------------------------------------------------
    book = data.get("orderbook") if isinstance(data.get("orderbook"), dict) else None
    if book is None:
        feeds["orderbook"] = {
            "source": _source(data, "orderbook_source"),
            "status": "UNAVAILABLE",
            "reason": "NO_ORDERBOOK_SNAPSHOT",
        }
    else:
        bids = book.get("bids") or []
        asks = book.get("asks") or []
        age = _age_ms(book.get("timestamp"), snapshot_ms)
        levels = len(bids) + len(asks)
        if age is None:
            status, reason = "UNKNOWN", "ORDERBOOK_TIMESTAMP_MISSING_OR_FUTURE"
        elif age > ORDERBOOK_FRESH_MAX_MS:
            status, reason = "STALE", "ORDERBOOK_OLDER_THAN_15S"
        elif levels <= 0:
            status, reason = "EMPTY", "NO_ORDERBOOK_LEVELS"
        else:
            status, reason = "AVAILABLE", None
        feeds["orderbook"] = {
            "source": _source(data, "orderbook_source", fallback="REST"),
            "status": status,
            "reason": reason,
            "age_ms": age,
            "samples": levels,
            "freshness": _freshness(age, ORDERBOOK_FRESH_MAX_MS),
        }

    # --- Recent executed trades --------------------------------------------
    trades = data.get("recent_trades") if isinstance(data.get("recent_trades"), list) else []
    trades_age = _age_ms(data.get("recent_trades_timestamp_ms"), snapshot_ms)
    if not trades:
        feeds["recent_trades"] = {
            "source": _source(data, "recent_trades_source"),
            "status": "UNAVAILABLE",
            "reason": "NO_RECENT_TRADES",
        }
    else:
        feeds["recent_trades"] = {
            "source": _source(data, "recent_trades_source", fallback="REST"),
            "status": "AVAILABLE" if trades_age is not None and trades_age <= TRADES_FRESH_MAX_MS else "STALE",
            "age_ms": trades_age,
            "samples": len(trades),
            "freshness": _freshness(trades_age, TRADES_FRESH_MAX_MS),
        }

    # --- CVD (timestamped trade batches) ------------------------------------
    batches = data.get("trade_flow_history") if isinstance(data.get("trade_flow_history"), list) else []
    if not batches:
        feeds["trade_flow_history"] = {
            "source": _source(data, "trade_flow_history_source"),
            "status": "UNAVAILABLE",
            "reason": "NO_TIMESTAMPED_TRADE_BATCHES",
        }
    else:
        feeds["trade_flow_history"] = {
            "source": _source(data, "trade_flow_history_source", fallback="WEBSOCKET"),
            "status": "AVAILABLE",
            "samples": len(batches),
        }

    # --- Liquidation events --------------------------------------------------
    events = data.get("liquidation_events") if isinstance(data.get("liquidation_events"), list) else []
    if not events:
        feeds["liquidation_events"] = {
            "source": _source(data, "liquidation_events_source"),
            "status": "UNAVAILABLE",
            "reason": "NO_EXCHANGE_LIQUIDATION_FEED",
        }
    else:
        newest = max((_finite_int(event.get("timestamp_ms")) for event in events if isinstance(event, dict)), default=None)
        age = _age_ms(newest, snapshot_ms)
        feeds["liquidation_events"] = {
            "source": _source(data, "liquidation_events_source", fallback="WEBSOCKET"),
            "status": "AVAILABLE" if age is not None else "UNKNOWN",
            "age_ms": age,
            "samples": len(events),
        }

    # --- Open interest: snapshot vs timestamped history are separate ----------
    oi_values = data.get("open_interest") if isinstance(data.get("open_interest"), list) else []
    oi_times = data.get("open_interest_timestamps_ms") if isinstance(data.get("open_interest_timestamps_ms"), list) else []
    timestamped_pairs = [
        (stamp, value)
        for stamp, value in zip(oi_times, oi_values)
        if _finite_int(stamp) is not None and _finite_float(value) is not None
    ]
    snapshot_only_values = max(0, len(oi_values) - len(oi_times))
    if len(timestamped_pairs) < MIN_TIMESTAMPED_OI_OBSERVATIONS:
        feeds["open_interest"] = {
            "source": _source(data, "open_interest_source"),
            "status": "INSUFFICIENT_OI_HISTORY",
            "reason": "SINGLE_OI_SNAPSHOT_CANNOT_ESTABLISH_CONTRACTION"
            if oi_values else "NO_TIMESTAMPED_OI_OBSERVATIONS",
            "samples": len(oi_values),
            "timestamped_samples": len(timestamped_pairs),
            "snapshot_only_samples": snapshot_only_values,
        }
    else:
        newest_oi = timestamped_pairs[-1][0]
        age = _age_ms(newest_oi, snapshot_ms)
        feeds["open_interest"] = {
            "source": _source(data, "open_interest_source", fallback="REST"),
            "status": "AVAILABLE",
            "age_ms": age,
            "freshness": _freshness(age, OI_FRESH_MAX_MS),
            "samples": len(oi_values),
            "timestamped_samples": len(timestamped_pairs),
            "snapshot_only_samples": snapshot_only_values,
        }

    # --- Funding rate ---------------------------------------------------------
    funding_raw = data.get("funding_rate") if isinstance(data.get("funding_rate"), list) else []
    funding = [value for value in funding_raw if not isinstance(value, list) and _finite_float(value) is not None]
    if not funding:
        feeds["funding_rate"] = {
            "source": _source(data, "funding_rate_source"),
            "status": "UNAVAILABLE",
            "reason": "NO_FUNDING_RATE_HISTORY",
        }
    else:
        feeds["funding_rate"] = {
            "source": _source(data, "funding_rate_source", fallback="REST"),
            "status": "AVAILABLE",
            "samples": len(funding),
        }

    # --- OHLCV candles ----------------------------------------------------------
    candles = {}
    for timeframe in ("15m", "1h", "4h", "1d", "1w"):
        series = data.get(timeframe) if isinstance(data.get(timeframe), list) else []
        candles[timeframe] = len(series)
    feeds["candles"] = {
        "source": "REST",
        "status": "AVAILABLE" if all(candles.get(tf) for tf in ("15m", "1h", "4h", "1d")) else "UNAVAILABLE",
        "reason": None if all(candles.get(tf) for tf in ("15m", "1h", "4h", "1d")) else "INCOMPLETE_OHLCV_TIMEFRAMES",
        "samples": sum(candles.values()),
        "timeframe_counts": candles,
    }

    # --- Correlation universe (BTC/ETH benchmark candles) ------------------------
    universe = data.get("correlation_universe") if isinstance(data.get("correlation_universe"), dict) else {}
    feeds["correlation_universe"] = {
        "source": "REST",
        "status": "AVAILABLE" if universe else "UNAVAILABLE",
        "reason": None if universe else "NO_BENCHMARK_CANDLES",
        "samples": sum(len(series) for series in universe.values() if isinstance(series, list)),
        "keys": sorted(universe.keys()),
    }

    return {
        "now_ms": snapshot_ms,
        "snapshot_timestamp_ms": snapshot_ms,
        "microstructure_source": _source(data, "microstructure_source", fallback="UNAVAILABLE"),
        "feeds": feeds,
    }
