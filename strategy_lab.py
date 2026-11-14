"""Independent seven-strategy analysis and selection for Atlas.

The lab is advisory: it never mutates the SMC result or sends exchange orders.
New strategy candidates are explicitly marked experimental until strategy-specific
backtests and outcome samples establish a reliable edge.
"""
from __future__ import annotations

import math
from statistics import median

from strategy_performance import evaluate_strategy_edge, rank_validated_candidate
from orderbook_engine import OrderBookEngine

_ORDERBOOK_ENGINE = OrderBookEngine()


STRATEGY_NAMES = {
    "trend_pullback": "Trend Following + Pullback",
    "volatility_breakout": "Volatility Breakout",
    "mean_reversion": "Mean Reversion",
    "liquidation_cascade": "Liquidation Cascade (OI proxy)",
    "orderflow_momentum": "Order Flow Momentum",
    "relative_strength": "Relative Strength",
    "smc": "SMC (mevcut Atlas)",
}


def _value(candle, name):
    try:
        value = float(getattr(candle, name))
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def _series(candles, field="close"):
    values = [_value(item, field) for item in (candles or [])]
    return [value for value in values if value is not None]


def _ema(values, period):
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1.0)
    result = sum(values[:period]) / period
    for value in values[period:]:
        result = alpha * value + (1.0 - alpha) * result
    return result


def _atr(candles, period=14):
    if len(candles) < period + 1:
        return None
    ranges = []
    for previous, current in zip(candles[-(period + 1):-1], candles[-period:]):
        high, low, prev_close = _value(current, "high"), _value(current, "low"), _value(previous, "close")
        if high is None or low is None or prev_close is None:
            return None
        ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    value = sum(ranges) / len(ranges) if ranges else None
    return value if value and math.isfinite(value) and value > 0 else None




def _adx(candles, period=14):
    if len(candles) < period * 2 + 1:
        return None
    plus_dm = []
    minus_dm = []
    true_ranges = []
    for previous, current in zip(candles[-(period * 2 + 1):-1], candles[-(period * 2):]):
        high = _value(current, "high")
        low = _value(current, "low")
        prev_high = _value(previous, "high")
        prev_low = _value(previous, "low")
        prev_close = _value(previous, "close")
        if None in (high, low, prev_high, prev_low, prev_close):
            return None
        up = high - prev_high
        down = prev_low - low
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    dx_values = []
    for index in range(len(true_ranges) - period + 1):
        tr = sum(true_ranges[index:index + period])
        if tr <= 0:
            continue
        plus = 100.0 * sum(plus_dm[index:index + period]) / tr
        minus = 100.0 * sum(minus_dm[index:index + period]) / tr
        denominator = plus + minus
        dx_values.append(100.0 * abs(plus - minus) / denominator if denominator > 0 else 0.0)
    return sum(dx_values[-period:]) / min(period, len(dx_values)) if dx_values else None

def _rsi(values, period=14):
    if len(values) < period + 1:
        return None
    changes = [right - left for left, right in zip(values[-(period + 1):-1], values[-period:])]
    gains = sum(max(change, 0.0) for change in changes) / period
    losses = sum(max(-change, 0.0) for change in changes) / period
    if losses <= 0:
        return 100.0 if gains > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + gains / losses)




def _vwap(candles):
    numerator = denominator = 0.0
    for candle in candles or []:
        high, low, close = (_value(candle, key) for key in ("high", "low", "close"))
        volume = _value(candle, "volume")
        if None in (high, low, close, volume) or volume < 0:
            return None
        typical = (high + low + close) / 3.0
        numerator += typical * volume
        denominator += volume
    if denominator <= 0:
        return None
    value = numerator / denominator
    return value if math.isfinite(value) and value > 0 else None

def _bollinger(values, period=20, deviations=2.0):
    if len(values) < period:
        return None
    sample = values[-period:]
    mean = sum(sample) / period
    variance = sum((item - mean) ** 2 for item in sample) / period
    sigma = math.sqrt(max(0.0, variance))
    return mean - deviations * sigma, mean, mean + deviations * sigma


def _valid_plan(direction, entry, stop, atr, candles, source, strength, entry_type="MARKET", entry_reference="LAST_CLOSED_15M_FALLBACK"):
    if direction not in {"LONG", "SHORT"} or not all(
        isinstance(value, (int, float)) and math.isfinite(value) and value > 0
        for value in (entry, stop, atr)
    ):
        return None
    risk = entry - stop if direction == "LONG" else stop - entry
    if risk <= 0 or risk < 0.75 * atr or risk > 3.0 * atr:
        return None
    # Prefer actual opposing swing-liquidity levels. Use transparent R-multiple
    # fallback only when the supplied history does not contain three valid levels.
    pivots = []
    sample = list(candles or [])[-120:]
    for index in range(2, len(sample) - 2):
        high = _value(sample[index], "high")
        low = _value(sample[index], "low")
        if high is None or low is None:
            continue
        left_highs = [_value(item, "high") for item in sample[index - 2:index]]
        right_highs = [_value(item, "high") for item in sample[index + 1:index + 3]]
        left_lows = [_value(item, "low") for item in sample[index - 2:index]]
        right_lows = [_value(item, "low") for item in sample[index + 1:index + 3]]
        if all(value is not None for value in left_highs + right_highs) and all(high > value for value in left_highs + right_highs):
            if direction == "LONG" and high > entry and (high - entry) / risk >= 1.25:
                pivots.append(high)
        if all(value is not None for value in left_lows + right_lows) and all(low < value for value in left_lows + right_lows):
            if direction == "SHORT" and low < entry and (entry - low) / risk >= 1.25:
                pivots.append(low)
    if direction == "LONG":
        structural = sorted(set(value for value in pivots if value > entry))
        targets = structural[:3] if len(structural) >= 3 else [entry + risk * multiple for multiple in (1.25, 2.0, 3.0)]
    else:
        structural = sorted(set((value for value in pivots if value < entry)), reverse=True)
        targets = structural[:3] if len(structural) >= 3 else [entry - risk * multiple for multiple in (1.25, 2.0, 3.0)]
    target_model = "SWING_LIQUIDITY" if len(structural) >= 3 else "R_MULTIPLE_FALLBACK"
    if any(value <= 0 for value in targets):
        return None
    # Bybit public-market fee proxy only; spread/slippage are not known here.
    fee_rate = 0.00055
    fee_r = (2.0 * fee_rate * entry) / risk
    if 1.25 - fee_r < 0.80:
        return None
    return {
        "status": "CANDIDATE",
        "strategy_id": source,
        "strategy": STRATEGY_NAMES[source],
        "direction": direction,
        "entry_type": entry_type,
        "entry_reference": entry_reference,
        "entry": round(entry, 10),
        "stop_loss": round(stop, 10),
        "tp1": round(targets[0], 10),
        "tp2": round(targets[1], 10),
        "tp3": round(targets[2], 10),
        "rr_tp1": 1.25,
        "rr_tp2": 2.0,
        "rr_tp3": 3.0,
        "estimated_fee_r": round(fee_r, 4),
        "estimated_net_rr_tp1": round(1.25 - fee_r, 4),
        "estimated_net_rr_tp3": round(3.0 - fee_r, 4),
        "strength": round(float(strength), 2),
        "target_model": target_model,
        "experimental": source != "smc",
        "reasons": [],
    }


def _current_price(data):
    try:
        value = float(data.get("current_price"))
    except (TypeError, ValueError, OverflowError):
        value = None
    if value is not None and math.isfinite(value) and value > 0:
        return value
    candles = data.get("15m") or []
    return _value(candles[-1], "close") if candles else None


def _entry_reference(data):
    return str(data.get("current_price_source") or "LAST_CLOSED_15M_FALLBACK")


def _regime(data):
    candles = data.get("4h") or []
    closes = _series(candles)
    atr = _atr(candles)
    fast, slow = _ema(closes, 20), _ema(closes, 50)
    if atr is None or fast is None or slow is None or not closes:
        return {"label": "UNKNOWN", "trend": "NEUTRAL", "strength": 0.0}
    distance = abs(fast - slow) / atr
    trend = "BULLISH" if fast > slow else "BEARISH" if fast < slow else "NEUTRAL"
    label = "TREND" if distance >= 0.65 else "RANGE"
    # A high-volatility flag requires a relative ATR expansion, not a fixed coin price threshold.
    atr_percentages = []
    for end in range(max(15, len(candles) - 80), len(candles) + 1):
        sample = candles[:end]
        sample_atr = _atr(sample)
        close = _value(sample[-1], "close") if sample else None
        if sample_atr and close and close > 0:
            atr_percentages.append(sample_atr / close)
    if len(atr_percentages) >= 10 and atr_percentages[-1] > median(atr_percentages[:-1]) * 1.5:
        label = "HIGH_VOLATILITY"
    return {"label": label, "trend": trend, "strength": round(distance, 3)}


def _trend_pullback(data):
    h4, h1 = data.get("4h") or [], data.get("1h") or []
    c4, c1 = _series(h4), _series(h1)
    atr = _atr(h1)
    if len(c4) < 60 or len(c1) < 30 or atr is None:
        return None
    e20, e50, e1 = _ema(c4, 20), _ema(c4, 50), _ema(c1, 20)
    adx_value = _adx(h4)
    e20_previous = _ema(c4[:-5], 20)
    if None in (e20, e50, e1, adx_value, e20_previous) or adx_value < 18:
        return None
    trend_slope = (e20 - e20_previous) / atr
    last, previous = h1[-1], h1[-2]
    close = _value(last, "close")
    prev_close = _value(previous, "close")
    low, high = _value(last, "low"), _value(last, "high")
    prev_low, prev_high = _value(previous, "low"), _value(previous, "high")
    if None in (close, prev_close, low, high, prev_low, prev_high):
        return None
    entry = _current_price(data)
    if entry is None:
        return None
    direction = None
    if e20 > e50 and entry > e1 and entry <= e1 + 1.25 * atr and (low <= e1 * 1.003 or prev_low <= e1 * 1.003) and close > prev_close:
        direction = "LONG"
        swing = min(_value(item, "low") for item in h1[-10:] if _value(item, "low") is not None)
        stop = min(entry - 1.0 * atr, swing - 0.1 * atr)
    elif e20 < e50 and entry < e1 and entry >= e1 - 1.25 * atr and (high >= e1 * 0.997 or prev_high >= e1 * 0.997) and close < prev_close:
        direction = "SHORT"
        swing = max(_value(item, "high") for item in h1[-10:] if _value(item, "high") is not None)
        stop = max(entry + 1.0 * atr, swing + 0.1 * atr)
    else:
        return None
    trend_separation = abs(e20 - e50) / atr
    pullback_distance = abs(entry - e1) / atr
    if (direction == "LONG" and trend_slope <= 0) or (direction == "SHORT" and trend_slope >= 0):
        return None
    strength = min(92.0, 62.0 + min(trend_separation * 5.0, 12.0) + min((adx_value - 18.0) * 0.5, 10.0) + max(0.0, 8.0 - pullback_distance * 6.0))
    plan = _valid_plan(direction, entry, stop, atr, h1, "trend_pullback", strength, entry_reference=_entry_reference(data))
    if plan:
        plan["reasons"] = ["4H EMA20/EMA50 alignment and positive EMA20 slope", f"4H ADX={adx_value:.1f}", "1H EMA20 pullback and candle reclaim"]
    return plan


def _volatility_breakout(data):
    candles = data.get("1h") or []
    closes = _series(candles)
    atr = _atr(candles)
    if len(candles) < 45 or atr is None:
        return None
    # Require pre-breakout volatility compression; the current breakout bar
    # must close outside the prior range, not merely wick through it.
    bandwidths = []
    for end in range(max(20, len(closes) - 41), len(closes) - 1):
        band = _bollinger(closes[end - 20:end])
        if band:
            bandwidths.append((band[2] - band[0]) / max(band[1], 1e-12))
    prior_band = _bollinger(closes[-21:-1])
    if not bandwidths or prior_band is None:
        return None
    prior_width = (prior_band[2] - prior_band[0]) / max(prior_band[1], 1e-12)
    if prior_width > sorted(bandwidths)[max(0, int((len(bandwidths) - 1) * 0.50))]:
        return None
    previous = candles[-21:-1]
    last = candles[-1]
    prior_highs = [_value(item, "high") for item in previous]
    prior_lows = [_value(item, "low") for item in previous]
    volumes = [_value(item, "volume") for item in candles[-21:-1]]
    close, volume = _value(last, "close"), _value(last, "volume")
    if close is None or volume is None or any(item is None for item in prior_highs + prior_lows + volumes):
        return None
    average_volume = sum(volumes) / len(volumes)
    entry = _current_price(data)
    if entry is None:
        return None
    direction = None
    if close > max(prior_highs) and entry >= close and entry <= max(prior_highs) + atr and volume >= average_volume * 1.2:
        direction = "LONG"
        stop = entry - 1.5 * atr
    elif close < min(prior_lows) and entry <= close and entry >= min(prior_lows) - atr and volume >= average_volume * 1.2:
        direction = "SHORT"
        stop = entry + 1.5 * atr
    else:
        return None
    boundary = max(prior_highs) if direction == "LONG" else min(prior_lows)
    volume_ratio = volume / average_volume if average_volume > 0 else 0.0
    breakout_distance = abs(entry - boundary) / atr
    strength = min(92.0, 65.0 + min(max(0.0, volume_ratio - 1.2) * 12.0, 15.0) + min(breakout_distance * 8.0, 10.0))
    plan = _valid_plan(direction, entry, stop, atr, candles, "volatility_breakout", strength, entry_reference=_entry_reference(data))
    if plan:
        plan["reasons"] = ["1H 20-candle closed breakout after volatility compression", "Volume at least 1.2x prior 20-candle average"]
    return plan


def _mean_reversion(data, regime):
    candles = data.get("15m") or []
    closes = _series(candles)
    atr = _atr(candles)
    bands = _bollinger(closes)
    rsi = _rsi(closes)
    if regime["label"] != "RANGE" or len(candles) < 25 or atr is None or bands is None or rsi is None:
        return None
    previous_bands = _bollinger(closes[:-1])
    if previous_bands is None:
        return None
    lower, _, upper = bands
    prev_lower, _, prev_upper = previous_bands
    previous, last = candles[-2], candles[-1]
    prev_close, close = _value(previous, "close"), _value(last, "close")
    if None in (prev_close, close):
        return None
    direction = None
    if prev_close < prev_lower and close > lower and rsi <= 42:
        direction = "LONG"
        stop = min(_value(item, "low") for item in candles[-5:] if _value(item, "low") is not None) - 0.15 * atr
    elif prev_close > prev_upper and close < upper and rsi >= 58:
        direction = "SHORT"
        stop = max(_value(item, "high") for item in candles[-5:] if _value(item, "high") is not None) + 0.15 * atr
    else:
        return None
    entry = _current_price(data)
    vwap = _vwap(candles[-20:])
    if entry is None or vwap is None:
        return None
    middle = bands[1]
    vwap_distance_atr = abs(entry - vwap) / atr
    if direction == "LONG":
        if not lower <= entry <= middle or entry >= vwap or not 0.25 <= vwap_distance_atr <= 2.5:
            return None
    else:
        if not middle <= entry <= upper or entry <= vwap or not 0.25 <= vwap_distance_atr <= 2.5:
            return None
    extremity = max(0.0, 42.0 - rsi) if direction == "LONG" else max(0.0, rsi - 58.0)
    strength = min(88.0, 65.0 + min(extremity * 0.5, 12.0) + min(abs(close - prev_close) / atr * 4.0, 8.0))
    plan = _valid_plan(direction, entry, stop, atr, candles, "mean_reversion", strength, entry_reference=_entry_reference(data))
    if plan:
        plan["reasons"] = ["15m Bollinger re-entry after outside close", f"RSI14={rsi:.1f}", f"VWAP deviation={vwap_distance_atr:.2f} ATR with mean-side confirmation", "Range regime"]
    return plan


def _trade_flow(data):
    """Return recent taker buy ratio using notional-weighted exchange trades."""
    trades = data.get("recent_trades") or []
    buy = sell = 0.0
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        try:
            amount = float(trade.get("amount") or 0)
            price = float(trade.get("price") or 0)
        except (TypeError, ValueError, OverflowError):
            continue
        if not (math.isfinite(amount) and math.isfinite(price) and amount > 0 and price > 0):
            continue
        notional = amount * price
        side = str(trade.get("side") or "").lower()
        if side == "buy":
            buy += notional
        elif side == "sell":
            sell += notional
    total = buy + sell
    return (buy / total if total > 0 else None), total


def _orderflow_momentum(data):
    book = data.get("orderbook")
    candles = data.get("15m") or []
    atr = _atr(candles)
    now_ms = int(data.get("snapshot_timestamp_ms") or 0)
    if not isinstance(book, dict) or atr is None or not candles or not now_ms:
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
    entry = _current_price(data)
    if close is None or opened is None or entry is None:
        return None
    direction = None
    if imbalance >= 0.18 and trade_delta >= 0.12 and close > opened and entry >= opened:
        direction = "LONG"
        stop = entry - 1.5 * atr
    elif imbalance <= -0.18 and trade_delta <= -0.12 and close < opened and entry <= opened:
        direction = "SHORT"
        stop = entry + 1.5 * atr
    else:
        return None

    strength = min(92.0, 65.0 + min(abs(imbalance) * 35.0, 15.0) + min(abs(trade_delta) * 25.0, 10.0))
    plan = _valid_plan(direction, entry, stop, atr, candles, "orderflow_momentum", strength, entry_reference=_entry_reference(data))
    if plan:
        plan["reasons"] = [
            f"Depth-weighted order-book notional imbalance={imbalance:+.2f}",
            f"Recent taker notional delta={trade_delta:+.2f}",
            f"Spread={spread_pct:.4f}%",
        ]
        plan["data_quality"] = "FRESH_BOOK_AND_NOTIONAL_TRADE_FLOW"
        plan["orderflow_metrics"] = {
            "bid_notional": flow.get("bid_notional"),
            "ask_notional": flow.get("ask_notional"),
            "trade_delta": trade_delta,
            "spread_pct": spread_pct,
            "trade_count": flow.get("trade_count"),
        }
    return plan


def _liquidation_cascade(data):
    candles = data.get("1h") or []
    oi = data.get("open_interest") or []
    atr = _atr(candles)
    if len(candles) < 20 or len(oi) < 2 or atr is None:
        return None
    try:
        previous_oi, current_oi = float(oi[-2]), float(oi[-1])
    except (TypeError, ValueError, OverflowError):
        return None
    if previous_oi <= 0 or not math.isfinite(previous_oi) or not math.isfinite(current_oi):
        return None
    oi_times = data.get("open_interest_timestamps_ms") or []
    now_ms = int(data.get("snapshot_timestamp_ms") or 0)
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
    oi_change = (current_oi - previous_oi) / previous_oi
    last = candles[-1]
    close, opened = _value(last, "close"), _value(last, "open")
    buy_ratio, _ = _trade_flow(data)
    entry = _current_price(data)
    if close is None or opened is None or entry is None:
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
    if oi_change <= -0.015 and close > opened and entry > opened and impulse >= 1.0 and buy_ratio is not None and buy_ratio >= 0.56 and funding <= 0.0003:
        direction = "LONG"
        stop = entry - 1.5 * atr
    elif oi_change <= -0.015 and close < opened and entry < opened and impulse >= 1.0 and buy_ratio is not None and buy_ratio <= 0.44 and funding >= -0.0003:
        direction = "SHORT"
        stop = entry + 1.5 * atr
    else:
        return None
    strength = min(92.0, 65.0 + min(abs(oi_change) * 400.0, 15.0) + min(impulse * 5.0, 10.0))
    plan = _valid_plan(direction, entry, stop, atr, candles, "liquidation_cascade", strength, entry_reference=_entry_reference(data))
    if plan:
        plan["reasons"] = [f"Open interest contraction={oi_change * 100:.2f}%", f"1H impulse={impulse:.2f} ATR", f"Funding rate={funding:.5f}", "Trade-flow confirmation; liquidation side remains a proxy inference"]
        plan["data_quality"] = "OI_CONTRACTION_PROXY_NOT_EXCHANGE_LIQUIDATION_FEED"
    return plan


def _relative_strength(data):
    candles = data.get("4h") or []
    closes = _series(candles)
    atr = _atr(candles)
    if len(closes) < 15 or atr is None:
        return None
    symbol = str(data.get("symbol") or "").upper()
    universe = data.get("correlation_universe") or {}
    benchmark_keys = ["ETH"] if symbol.startswith("BTC/") else ["BTC"] if symbol.startswith("ETH/") else ["BTC", "ETH"]
    benchmark_returns = []
    try:
        own_time = int(candles[-1].time)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None
    for benchmark_key in benchmark_keys:
        benchmark_candles = universe.get(benchmark_key) or []
        benchmark_closes = _series(benchmark_candles)
        if len(benchmark_closes) < 15:
            return None
        try:
            benchmark_time = int(benchmark_candles[-1].time)
        except (AttributeError, TypeError, ValueError, OverflowError):
            return None
        if abs(own_time - benchmark_time) > 4 * 60 * 60 * 1000:
            return None
        benchmark_returns.append(benchmark_closes[-1] / benchmark_closes[-13] - 1.0)
    own_return = closes[-1] / closes[-13] - 1.0
    benchmark_return = sum(benchmark_returns) / len(benchmark_returns)
    relative = own_return - benchmark_return
    e20 = _ema(closes, 20)
    if e20 is None:
        return None
    direction = "LONG" if relative >= 0.02 and closes[-1] > e20 else "SHORT" if relative <= -0.02 and closes[-1] < e20 else None
    if not direction:
        return None
    entry = _current_price(data)
    if entry is None or (direction == "LONG" and entry <= e20) or (direction == "SHORT" and entry >= e20):
        return None
    stop = entry - 1.5 * atr if direction == "LONG" else entry + 1.5 * atr
    strength = min(88.0, 65.0 + min(abs(relative) * 500.0, 20.0))
    plan = _valid_plan(direction, entry, stop, atr, candles, "relative_strength", strength, entry_reference=_entry_reference(data))
    if plan:
        plan["reasons"] = [f"12x4H relative return vs {benchmark}={relative * 100:+.2f}%", f"Price/EMA20 alignment"]
    return plan


def _smc_candidate(result):
    if not isinstance(result, dict):
        return None
    try:
        from utils.signal_card import build_signal_card
        card = build_signal_card(result)
    except Exception:
        return None
    if card.get("decision_action") not in {"EXECUTE", "EXECUTE_WITH_CAUTION"}:
        return None
    direction = str(card.get("direction") or "").upper()
    entry, stop = card.get("entry"), card.get("stop_loss")
    targets = card.get("tp_levels") or []
    if direction not in {"LONG", "SHORT"} or not entry or not stop or not targets:
        return None
    try:
        entry, stop = float(entry), float(stop)
        target_values = [float(item.get("price") if isinstance(item, dict) else item) for item in targets[:3]]
    except (TypeError, ValueError, OverflowError):
        return None
    if not target_values:
        return None
    if not all(math.isfinite(value) and value > 0 for value in [entry, stop, *target_values]):
        return None
    if direction == "LONG" and not (stop < entry < target_values[0] and all(left < right for left, right in zip(target_values, target_values[1:]))):
        return None
    if direction == "SHORT" and not (target_values[0] < entry < stop and all(left > right for left, right in zip(target_values, target_values[1:]))):
        return None
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    plan = {
        "status": "CANDIDATE", "strategy_id": "smc", "strategy": STRATEGY_NAMES["smc"],
        "direction": direction, "entry_type": card.get("entry_type") or "LIMIT",
        "entry": entry, "stop_loss": stop,
        "tp1": target_values[0], "tp2": target_values[1] if len(target_values) > 1 else None,
        "tp3": target_values[2] if len(target_values) > 2 else None,
        "rr_tp1": round(abs(target_values[0] - entry) / risk, 3),
        "rr_tp2": round(abs(target_values[1] - entry) / risk, 3) if len(target_values) > 1 else None,
        "rr_tp3": round(abs(target_values[2] - entry) / risk, 3) if len(target_values) > 2 else None,
        "strength": float(card.get("setup_quality") or card.get("confidence") or 0),
        "target_model": "SMC_STRUCTURAL",
        "experimental": False,
        "reasons": ["Mevcut Atlas SMC karar motoru EXECUTE üretti"],
    }
    plan["estimated_net_rr"] = card.get("net_rr")
    return plan


def _regime_fit(strategy_id, regime):
    label, trend = regime.get("label"), regime.get("trend")
    preferred = {
        "trend_pullback": {"TREND": 1.0},
        "volatility_breakout": {"HIGH_VOLATILITY": 1.0, "TREND": 0.85},
        "mean_reversion": {"RANGE": 1.0},
        "liquidation_cascade": {"HIGH_VOLATILITY": 1.0},
        "orderflow_momentum": {"TREND": 0.9, "HIGH_VOLATILITY": 1.0},
        "relative_strength": {"TREND": 0.9, "HIGH_VOLATILITY": 0.75},
        "smc": {"TREND": 0.85, "RANGE": 0.85, "HIGH_VOLATILITY": 0.85, "UNKNOWN": 0.75},
    }
    fit = preferred.get(strategy_id, {}).get(label, 0.55)
    if strategy_id == "trend_pullback":
        if (trend == "BULLISH" and regime.get("label") == "TREND") or (trend == "BEARISH" and regime.get("label") == "TREND"):
            fit = 1.0
    return fit


class SevenStrategyLab:
    """Run six independent experimental strategies plus the existing SMC plan."""

    def analyze(self, data, smc_result=None, performance_by_strategy=None):
        regime = _regime(data)
        evaluators = {
            "trend_pullback": lambda: _trend_pullback(data),
            "volatility_breakout": lambda: _volatility_breakout(data),
            "mean_reversion": lambda: _mean_reversion(data, regime),
            "liquidation_cascade": lambda: _liquidation_cascade(data),
            "orderflow_momentum": lambda: _orderflow_momentum(data),
            "relative_strength": lambda: _relative_strength(data),
            "smc": lambda: _smc_candidate(smc_result),
        }
        results = []
        for strategy_id, evaluator in evaluators.items():
            try:
                candidate = evaluator()
                if candidate is None:
                    results.append({
                        "strategy_id": strategy_id,
                        "strategy": STRATEGY_NAMES[strategy_id],
                        "status": "NO_SETUP",
                        "reason": "Strateji koşulları oluşmadı veya gerekli veri yok.",
                    })
                    continue
                fit = _regime_fit(strategy_id, regime)
                candidate["regime_fit"] = round(fit, 3)
                candidate["selection_score"] = round(candidate["strength"] * fit, 2)
                results.append(candidate)
            except Exception as exc:
                results.append({
                    "strategy_id": strategy_id,
                    "strategy": STRATEGY_NAMES[strategy_id],
                    "status": "ERROR",
                    "reason": f"{type(exc).__name__}: {exc}",
                })

        candidates = [item for item in results if item.get("status") == "CANDIDATE"]
        performance_by_strategy = performance_by_strategy or {}
        validated = []
        for candidate in candidates:
            strategy_id = candidate["strategy_id"]
            stats = performance_by_strategy.get(strategy_id)
            edge = evaluate_strategy_edge(stats)
            candidate["edge_validation"] = edge
            if strategy_id != "smc" and edge["eligible"]:
                ranked = rank_validated_candidate(candidate, stats, candidate.get("regime_fit", 1.0))
                if ranked:
                    candidate["validated_selection_score"] = ranked["score"]
                    validated.append(candidate)
        # The existing SMC decision remains a compatibility fallback. Experimental
        # engines cannot displace it until independent, cost-adjusted OOS evidence
        # clears the statistical promotion gates.
        validated.sort(key=lambda item: item.get("validated_selection_score", 0.0), reverse=True)
        smc_candidate = next((item for item in candidates if item.get("strategy_id") == "smc"), None)
        selected = validated[0] if validated else smc_candidate
        return {
            "version": 2,
            "symbol": data.get("symbol"),
            "regime": regime,
            "strategies": results,
            "candidate_count": len(candidates),
            "validated_candidate_count": len(validated),
            "selected": selected,
            "selection_method": "out_of_sample_edge_gated_with_legacy_smc_fallback",
            "performance_status": "VALIDATED_EXPERIMENTAL_EDGE_AVAILABLE" if validated else "NO_EXPERIMENTAL_EDGE_VALIDATED",
            "warning": (
                "Deneysel motorlar yalnızca stratejiye özel, maliyet sonrası ve out-of-sample "
                "performans yeterli örneklem ve güven sınırlarını geçerse SMC'nin önüne geçebilir. "
                "Performans kaydı yoksa deneysel aday seçilmez. OI contraction gerçek likidasyon "
                "akışı değildir; spread/slippage/funding modeli olmayan sonuçlar doğrulanmış sayılmaz."
            ),
        }
