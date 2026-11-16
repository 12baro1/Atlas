"""Shared microstructure evidence calculations over observed exchange data."""
from __future__ import annotations

import math

from shared.analysis_context import cached_analysis


@cached_analysis
def _finite(value):
    try:
        result=float(value)
        return result if math.isfinite(result) else None
    except (TypeError,ValueError,OverflowError):
        return None


@cached_analysis
def cumulative_volume_delta(trade_batches):
    """CVD from timestamped batches with explicit buy/sell aggressor notionals."""
    batches=list(trade_batches or [])
    if not batches:
        return {"state":"UNAVAILABLE","reason":"NO_HISTORICAL_TRADE_BATCHES"}
    cumulative=0.0
    series=[]
    for batch in batches:
        if not isinstance(batch,dict):
            return {"state":"INVALID_DATA"}
        buy=_finite(batch.get("buy_notional"))
        sell=_finite(batch.get("sell_notional"))
        timestamp=batch.get("timestamp_ms")
        try: timestamp=int(timestamp)
        except (TypeError,ValueError,OverflowError): return {"state":"INVALID_DATA"}
        if buy is None or sell is None or buy<0 or sell<0:
            return {"state":"INVALID_DATA"}
        cumulative += buy-sell
        series.append({"timestamp_ms":timestamp,"cvd":cumulative,"delta":buy-sell})
    return {"state":"AVAILABLE","series":series,"net_delta":cumulative,
            "direction":"BUY_DOMINANT" if cumulative>0 else "SELL_DOMINANT" if cumulative<0 else "BALANCED"}


@cached_analysis
def liquidation_events(events, now_ms=None, max_age_ms=900000):
    """Validate actual events and normalize Gate order side to liquidated position."""
    rows = list(events or [])
    if not rows:
        return {"state": "UNAVAILABLE", "reason": "NO_EXCHANGE_LIQUIDATION_FEED"}
    accepted = []
    for event in rows:
        if not isinstance(event, dict):
            return {"state": "INVALID_DATA"}
        timestamp = event.get("timestamp_ms")
        notional = _finite(event.get("notional"))
        position_side = str(event.get("position_side") or "").upper()
        order_side = str(event.get("order_side") or "").upper()
        if position_side not in ("LONG", "SHORT"):
            if order_side in ("BUY", "SELL"):
                position_side = "SHORT" if order_side == "BUY" else "LONG"
            else:
                legacy_side = str(event.get("side") or "").upper()
                position_side = {"BUY": "LONG", "SELL": "SHORT"}.get(legacy_side)
        try:
            timestamp = int(timestamp)
        except (TypeError, ValueError, OverflowError):
            return {"state": "INVALID_DATA"}
        if notional is None or notional <= 0 or position_side not in ("LONG", "SHORT"):
            return {"state": "INVALID_DATA"}
        if now_ms is not None:
            age = int(now_ms) - timestamp
            if age < 0 or age > max_age_ms:
                continue
        accepted.append({"timestamp_ms": timestamp, "notional": notional,
                         "position_side": position_side})
    if not accepted:
        return {"state": "STALE_OR_EMPTY"}
    long_liq = sum(row["notional"] for row in accepted if row["position_side"] == "LONG")
    short_liq = sum(row["notional"] for row in accepted if row["position_side"] == "SHORT")
    return {"state": "AVAILABLE", "events": len(accepted),
            "long_liquidation_notional": long_liq,
            "short_liquidation_notional": short_liq,
            "total_notional": long_liq + short_liq}


@cached_analysis
def beta_stability(asset_returns, benchmark_returns, window=24):
    """Compare rolling beta estimates; insufficient or unstable samples fail closed."""
    a=list(asset_returns or []); b=list(benchmark_returns or [])
    if len(a)!=len(b) or len(a)<window*2:
        return {"state":"UNAVAILABLE"}
    def beta(x,y):
        mx=sum(x)/len(x); my=sum(y)/len(y)
        variance=sum((v-my)**2 for v in y)
        if variance<=1e-12: return None
        value=sum((u-mx)*(v-my) for u,v in zip(x,y))/variance
        return value if math.isfinite(value) else None
    first=beta(a[-2*window:-window],b[-2*window:-window])
    second=beta(a[-window:],b[-window:])
    if first is None or second is None: return {"state":"UNAVAILABLE"}
    change=abs(second-first)
    return {"state":"STABLE" if change<=0.5 else "UNSTABLE",
            "previous_beta":round(first,4),"current_beta":round(second,4),
            "absolute_change":round(change,4)}


@cached_analysis
def relative_volume(current_volume, historical_volumes):
    values=[_finite(x) for x in (historical_volumes or [])]
    current=_finite(current_volume)
    if current is None or current<0 or len(values)<10 or any(x is None or x<0 for x in values):
        return {"state":"UNAVAILABLE"}
    baseline=sum(values)/len(values)
    if baseline<=0: return {"state":"FLAT_BASELINE"}
    ratio=current/baseline
    return {"state":"HIGH" if ratio>=1.5 else "LOW" if ratio<=0.7 else "NORMAL",
            "ratio":round(ratio,4)}
