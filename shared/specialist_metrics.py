"""Read-only market specialists. They never issue trade candidates."""
from __future__ import annotations

import math

from shared.analysis_services import _value


def _returns(candles):
    result = {}
    for before, after in zip(candles or (), (candles or ())[1:]):
        old, new = _value(before, "close"), _value(after, "close")
        stamp = getattr(after, "time", None)
        if old is None or new is None or old <= 0 or stamp is None:
            continue
        change = new / old - 1.0
        if math.isfinite(change):
            result[int(stamp)] = change
    return result


def analyze_relative_strength(data):
    """Timestamp-aligned, beta-adjusted returns against BTC/ETH benchmarks."""
    own = _returns(data.get("4h") or [])
    symbol = str(data.get("symbol") or "").upper()
    keys = ("ETH",) if symbol.startswith("BTC/") else ("BTC",) if symbol.startswith("ETH/") else ("BTC", "ETH")
    universe = data.get("correlation_universe") or {}
    benchmarks = [_returns(universe.get(key) or []) for key in keys]
    if len(own) < 48 or any(len(series) < 48 for series in benchmarks):
        return {"state": "INSUFFICIENT_HISTORY", "direction": "NEUTRAL", "sample_count": 0}
    stamps = sorted(set(own).intersection(*(set(series) for series in benchmarks)))[-48:]
    if len(stamps) < 48:
        return {"state": "INSUFFICIENT_ALIGNED_HISTORY", "direction": "NEUTRAL", "sample_count": len(stamps)}
    asset = [own[t] for t in stamps]
    market = [sum(series[t] for series in benchmarks) / len(benchmarks) for t in stamps]
    market_mean = sum(market) / len(market)
    asset_mean = sum(asset) / len(asset)
    variance = sum((x - market_mean) ** 2 for x in market)
    if variance <= 1e-12:
        return {"state": "UNRELIABLE_BENCHMARK", "direction": "NEUTRAL", "sample_count": len(stamps)}
    beta = sum((a - asset_mean) * (m - market_mean) for a, m in zip(asset, market)) / variance
    alpha = sum(asset[-12:]) - beta * sum(market[-12:])
    return {"state": "AVAILABLE", "direction": "LONG" if alpha > 0 else "SHORT" if alpha < 0 else "NEUTRAL",
            "beta": round(beta, 5), "relative_alpha_12x4h": round(alpha, 6),
            "sample_count": len(stamps), "source": "TIMESTAMP_ALIGNED_4H_RETURNS"}


def analyze_liquidation_pressure(data):
    """OI/funding pressure proxy; never label OI change as confirmed liquidation."""
    shared = data.get("shared_market_evidence") or {}
    oi = shared.get("open_interest") or {}
    funding = shared.get("funding") or {}
    change = oi.get("change_pct")
    if oi.get("state") != "FRESH" or change is None:
        return {"state": "UNAVAILABLE", "direction": "NEUTRAL", "source": "OI_PROXY_NOT_LIQUIDATION_EVENTS"}
    try:
        change = float(change)
    except (ValueError, TypeError, OverflowError):
        return {"state": "INVALID_DATA", "direction": "NEUTRAL"}
    if not math.isfinite(change):
        return {"state": "INVALID_DATA", "direction": "NEUTRAL"}
    return {"state": "AVAILABLE", "direction": "NEUTRAL", "oi_change_pct": round(change, 5),
            "funding_rate": funding.get("latest") if funding.get("state") == "FRESH" else None,
            "source": "OI_PROXY_NOT_LIQUIDATION_EVENTS"}
