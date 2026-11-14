"""Seven raw setup generators, one shared eligibility filter, one final selector.

The seven sources include one integrated SMC setup assembled by Atlas's SMC
specialist world. Specialist motors are evidence producers inside that SMC world,
not additional strategy candidates or independent trade-decision authorities.
"""
from __future__ import annotations

import math
from statistics import median

from orderbook_engine import OrderBookEngine
from risk_engine import RiskEngine
from config import Config

_ORDERBOOK_ENGINE = OrderBookEngine()


def _configured_partial_tp_weights():
    raw = getattr(Config, "SIGNAL_OUTCOME_PARTIAL_WEIGHTS", "0.5,0.3,0.2")
    if isinstance(raw, dict):
        values = [raw.get(f"tp{i}", 1.0) for i in range(1, 4)]
    elif isinstance(raw, str):
        values = raw.split(",")
    elif isinstance(raw, (list, tuple)):
        values = list(raw)
    else:
        values = []
    weights = {}
    for index in range(3):
        value = values[index] if index < len(values) else 1.0
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            number = 0.0
        weights[f"tp{index + 1}"] = number if math.isfinite(number) and number > 0 else 0.0
    return weights if sum(weights.values()) > 0 else {"tp1": 1.0, "tp2": 1.0, "tp3": 1.0}


STRATEGY_NAMES = {
    "trend_pullback": "Trend Following + Pullback",
    "volatility_breakout": "Volatility Breakout",
    "mean_reversion": "Mean Reversion",
    "liquidation_cascade": "Liquidation Cascade (OI proxy)",
    "orderflow_momentum": "Order Flow Momentum",
    "relative_strength": "Relative Strength",
    "smc": "SMC (bütünleşik uzman motorları)",
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


def _risk_validate_candidate(candidate):
    """Apply the same final RR and execution-friction model used by SMC risk."""
    try:
        entry = float(candidate.get("entry"))
        stop = float(candidate.get("stop_loss"))
        targets = {key: float(candidate.get(key)) for key in ("tp1", "tp2", "tp3")}
        risk = {
            "entry_type": str(candidate.get("entry_type") or "MARKET").upper(),
            "side": str(candidate.get("direction") or "").upper(),
            "atr": candidate.get("atr"),
            "risk_setup_valid": True,
            "minimum_net_rr": float(Config.MINIMUM_NET_RR),
            "risk_percent_base": float(Config.RISK_PERCENT),
            "position_size_limit": float(Config.MAX_POSITION_SIZE),
        }
        reconciled = RiskEngine().reconcile_final_geometry_payload(risk, entry, stop, targets)
        net_rr = reconciled.get("weighted_net_rr")
        net_rr = float(net_rr) if net_rr is not None else None
        eligible = (
            reconciled.get("risk_setup_valid") is True
            and net_rr is not None and math.isfinite(net_rr)
            and net_rr >= float(Config.MINIMUM_NET_RR)
            and reconciled.get("final_geometry_reconciled") is True
        )
        return {
            "eligible": bool(eligible),
            "reason": None if eligible else (
                reconciled.get("risk_setup_reason")
                or f"Common net-RR/stop-cost gate failed (net RR={net_rr})"
            ),
            "weighted_net_rr": net_rr,
            "risk_plan": reconciled,
        }
    except Exception as exc:
        return {"eligible": False, "reason": f"risk validation error: {type(exc).__name__}: {exc}", "weighted_net_rr": None, "risk_plan": None}


def _valid_plan(direction, entry, stop, atr, candles, source, strength, entry_type="MARKET", entry_reference="LAST_CLOSED_15M_FALLBACK"):
    if direction not in {"LONG", "SHORT"} or not all(
        isinstance(value, (int, float)) and math.isfinite(value) and value > 0
        for value in (entry, stop, atr)
    ):
        return None
    risk_distance = entry - stop if direction == "LONG" else stop - entry
    if risk_distance <= 0:
        return None
    # Stop-distance policy belongs to the shared filter, not an individual strategy.
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
            if direction == "LONG" and high > entry and (high - entry) / risk_distance >= 1.25:
                pivots.append(high)
        if all(value is not None for value in left_lows + right_lows) and all(low < value for value in left_lows + right_lows):
            if direction == "SHORT" and low < entry and (entry - low) / risk_distance >= 1.25:
                pivots.append(low)
    if direction == "LONG":
        structural = sorted(set(value for value in pivots if value > entry))
        targets = structural[:3] if len(structural) >= 3 else [entry + risk_distance * multiple for multiple in (2.0, 3.0, 4.0)]
    else:
        structural = sorted(set((value for value in pivots if value < entry)), reverse=True)
        targets = structural[:3] if len(structural) >= 3 else [entry - risk_distance * multiple for multiple in (2.0, 3.0, 4.0)]
    target_model = "SWING_LIQUIDITY" if len(structural) >= 3 else "R_MULTIPLE_FALLBACK"
    if any(value <= 0 for value in targets):
        return None
    rr_values = [abs(value - entry) / risk_distance for value in targets]
    plan = {
        "status": "CANDIDATE", "strategy_id": source, "strategy": STRATEGY_NAMES[source],
        "direction": direction, "entry_type": str(entry_type or "MARKET").upper(),
        "entry_reference": entry_reference, "entry": round(entry, 10), "atr": round(atr, 10),
        "stop_loss": round(stop, 10), "tp1": round(targets[0], 10),
        "tp2": round(targets[1], 10), "tp3": round(targets[2], 10),
        "rr_tp1": round(rr_values[0], 4), "rr_tp2": round(rr_values[1], 4),
        "rr_tp3": round(rr_values[2], 4), "strength": round(float(strength), 2),
        "target_model": target_model, "experimental": source != "smc", "reasons": [],
    }
    # No risk, fee, minimum-RR, or performance gate is allowed inside a
    # strategy. Every geometrically describable setup reaches the shared gate.
    plan["partial_exit_weights"] = _configured_partial_tp_weights()
    return plan

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
    entry = _current_price(data)
    if close is None or opened is None or entry is None:
        return None
    absorption = _absorption_proxy(flow, last, atr)
    direction = None
    if absorption == "BUYER_FLOW_ABSORBED":
        direction = "SHORT"
        stop = entry + 1.5 * atr
    elif absorption == "SELLER_FLOW_ABSORBED":
        direction = "LONG"
        stop = entry - 1.5 * atr
    elif imbalance >= 0.18 and trade_delta >= 0.12 and close > opened and entry >= opened:
        direction = "LONG"
        stop = entry - 1.5 * atr
    elif imbalance <= -0.18 and trade_delta <= -0.12 and close < opened and entry <= opened:
        direction = "SHORT"
        stop = entry + 1.5 * atr
    else:
        return None

    strength = min(92.0, 65.0 + min(abs(imbalance) * 35.0, 15.0) + min(abs(trade_delta) * 25.0, 10.0))
    if absorption:
        strength = min(94.0, strength + 2.0)
    plan = _valid_plan(direction, entry, stop, atr, candles, "orderflow_momentum", strength, entry_reference=_entry_reference(data))
    if plan:
        plan["reasons"] = [
            f"Depth-weighted order-book notional imbalance={imbalance:+.2f}",
            f"Recent taker notional delta={trade_delta:+.2f}",
            f"Spread={spread_pct:.4f}%",
        ]
        plan["data_quality"] = "ABSORPTION_PROXY" if absorption else "FRESH_BOOK_AND_NOTIONAL_TRADE_FLOW"
        if absorption:
            plan["reasons"].append(f"Absorption proxy: {absorption}")
        plan["orderflow_metrics"] = {
            "bid_notional": flow.get("bid_notional"),
            "ask_notional": flow.get("ask_notional"),
            "trade_delta": trade_delta,
            "spread_pct": spread_pct,
            "trade_count": flow.get("trade_count"),
            "absorption_proxy": absorption,
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
    """Beta-adjusted relative strength versus market and optional sector peers."""
    candles = data.get("4h") or []
    closes = _series(candles)
    atr = _atr(candles)
    if len(closes) < 55 or atr is None:
        return None
    symbol = str(data.get("symbol") or "").upper()
    universe = data.get("correlation_universe") or {}
    benchmark_keys = ["ETH"] if symbol.startswith("BTC/") else ["BTC"] if symbol.startswith("ETH/") else ["BTC", "ETH"]

    def returns_by_time(series):
        output = {}
        for previous, current in zip(series, series[1:]):
            previous_close = _value(previous, "close")
            current_close = _value(current, "close")
            try:
                timestamp = int(current.time)
            except (AttributeError, TypeError, ValueError, OverflowError):
                continue
            if previous_close and current_close and previous_close > 0:
                value = current_close / previous_close - 1.0
                if math.isfinite(value):
                    output[timestamp] = value
        return output

    own_returns = returns_by_time(candles)
    benchmark_maps = []
    for benchmark_key in benchmark_keys:
        benchmark_candles = universe.get(benchmark_key) or []
        if len(benchmark_candles) < 55:
            return None
        benchmark_maps.append(returns_by_time(benchmark_candles))
    common_times = set(own_returns)
    for values in benchmark_maps:
        common_times.intersection_update(values)
    if len(common_times) < 48:
        return None

    market_by_time = {
        timestamp: sum(values[timestamp] for values in benchmark_maps) / len(benchmark_maps)
        for timestamp in common_times
    }
    sector_maps = []
    for frames in (data.get("sector_peer_universe") or {}).values():
        peer_candles = frames.get("4h") if isinstance(frames, dict) else frames
        if peer_candles and len(peer_candles) >= 55:
            sector_maps.append(returns_by_time(peer_candles))
    sector_coverage = {}
    if len(sector_maps) >= 2:
        for timestamp in common_times:
            peer_values = [values[timestamp] for values in sector_maps if timestamp in values]
            if len(peer_values) >= 2:
                sector_coverage[timestamp] = sum(peer_values) / len(peer_values)
    use_sector = len(sector_maps) >= 2 and len(sector_coverage) >= int(len(common_times) * 0.70)
    aligned_times = sorted(
        timestamp for timestamp in common_times
        if not use_sector or timestamp in sector_coverage
    )
    benchmark_returns = [
        0.70 * market_by_time[timestamp] + 0.30 * sector_coverage[timestamp]
        if use_sector else market_by_time[timestamp]
        for timestamp in aligned_times
    ]
    asset_returns = [own_returns[timestamp] for timestamp in aligned_times]
    if len(asset_returns) < 48:
        return None

    # Estimate beta over the prior 48 closed 4H return observations.
    beta_asset = asset_returns[-48:]
    beta_market = benchmark_returns[-48:]
    mean_asset = sum(beta_asset) / len(beta_asset)
    mean_market = sum(beta_market) / len(beta_market)
    variance = sum((value - mean_market) ** 2 for value in beta_market)
    if variance <= 1e-12:
        return None
    covariance = sum(
        (asset_value - mean_asset) * (market_value - mean_market)
        for asset_value, market_value in zip(beta_asset, beta_market)
    )
    beta = covariance / variance
    if not math.isfinite(beta) or abs(beta) > 5.0:
        return None

    own_return_12 = sum(asset_returns[-12:])
    benchmark_return_12 = sum(benchmark_returns[-12:])
    residual_alpha = own_return_12 - beta * benchmark_return_12
    e20 = _ema(closes, 20)
    if e20 is None:
        return None
    direction = (
        "LONG" if residual_alpha >= 0.02 and closes[-1] > e20
        else "SHORT" if residual_alpha <= -0.02 and closes[-1] < e20
        else None
    )
    if not direction:
        return None
    entry = _current_price(data)
    if entry is None or (direction == "LONG" and entry <= e20) or (direction == "SHORT" and entry >= e20):
        return None
    stop = entry - 1.5 * atr if direction == "LONG" else entry + 1.5 * atr
    strength = min(90.0, 64.0 + min(abs(residual_alpha) * 450.0, 22.0) + min(abs(beta) * 2.0, 4.0))
    plan = _valid_plan(direction, entry, stop, atr, candles, "relative_strength", strength, entry_reference=_entry_reference(data))
    if plan:
        benchmark_label = "/".join(benchmark_keys)
        sector_label = f" + sector peers ({len(sector_maps)})" if use_sector else ""
        plan["reasons"] = [
            f"12x4H beta-adjusted residual alpha={residual_alpha * 100:+.2f}%",
            f"Estimated beta={beta:.2f} vs {benchmark_label}{sector_label}",
            "Absolute EMA20 trend confirmation",
        ]
        plan["relative_strength_metrics"] = {
            "beta": round(beta, 4),
            "residual_alpha_12x4h": round(residual_alpha, 6),
            "market_return_12x4h": round(benchmark_return_12, 6),
            "sector_peers_used": len(sector_maps) if use_sector else 0,
        }
    return plan


def _absorption_proxy(flow, candle, atr):
    """Infer passive absorption from aggressive trade delta plus stalled price.

    This is a snapshot proxy, not proof of hidden liquidity or queue replenishment.
    """
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

def _smc_candidate(result):
    """Build the single SMC setup from the integrated SMC specialist world.

    This adapter reads the pre-selector SMC entry/risk geometry. It deliberately
    does not inspect the legacy signal or decision verdict: those are downstream
    gates and must not suppress an otherwise valid SMC setup before the shared
    seven-strategy filter gets to evaluate it.
    """
    if not isinstance(result, dict):
        return None
    analysis = result.get("analysis") if isinstance(result.get("analysis"), dict) else {}
    entry_state = analysis.get("entry") if isinstance(analysis.get("entry"), dict) else result.get("entry")
    entry_state = entry_state if isinstance(entry_state, dict) else {}
    source_risk = result.get("risk") if isinstance(result.get("risk"), dict) else {}
    dynamic_tp = result.get("dynamic_tp") if isinstance(result.get("dynamic_tp"), dict) else {}
    signal = result.get("signal") if isinstance(result.get("signal"), dict) else {}
    direction = str(entry_state.get("direction") or signal.get("signal") or "").upper()
    try:
        entry_value = entry_state.get("entry")
        if entry_value is None:
            entry_value = source_risk.get("entry")
        stop_value = source_risk.get("stop_loss")
        if stop_value is None:
            stop_value = entry_state.get("stop_loss")
        entry = float(entry_value)
        stop = float(stop_value)
        target_values = [
            float(source_risk.get(key) if source_risk.get(key) is not None else dynamic_tp.get(key))
            for key in ("tp1", "tp2", "tp3")
        ]
    except (TypeError, ValueError, OverflowError):
        return None
    if direction not in {"LONG", "SHORT"} or not all(
        math.isfinite(value) and value > 0 for value in (entry, stop, *target_values)
    ):
        return None
    if direction == "LONG" and not (stop < entry < target_values[0] <= target_values[1] <= target_values[2]):
        return None
    if direction == "SHORT" and not (target_values[0] >= target_values[1] >= target_values[2] and target_values[0] < entry < stop):
        return None
    risk_distance = abs(entry - stop)
    if risk_distance <= 0:
        return None
    reasoning = entry_state.get("setup_reasoning") if isinstance(entry_state.get("setup_reasoning"), dict) else {}
    reasons = list(reasoning.get("supporting_evidence") or [])
    if reasoning.get("thesis"):
        reasons.insert(0, str(reasoning["thesis"]))
    if not reasons:
        reasons = ["Integrated SMC specialist evidence"]
    plan = {
        "status": "RAW_SETUP",
        "strategy_id": "smc",
        "strategy": STRATEGY_NAMES["smc"],
        "direction": direction,
        "entry_type": str(entry_state.get("entry_type") or "MARKET").upper(),
        "entry": entry,
        "stop_loss": stop,
        "tp1": target_values[0],
        "tp2": target_values[1],
        "tp3": target_values[2],
        "rr_tp1": round(abs(target_values[0] - entry) / risk_distance, 3),
        "rr_tp2": round(abs(target_values[1] - entry) / risk_distance, 3),
        "rr_tp3": round(abs(target_values[2] - entry) / risk_distance, 3),
        "strength": float(signal.get("confidence") or (analysis.get("setup_quality") or {}).get("score") or 0),
        "target_model": "SMC_STRUCTURAL",
        "experimental": False,
        "reasons": reasons,
        "supporting_event_ids": list(reasoning.get("supporting_event_ids") or []),
        "opposing_event_ids": list(reasoning.get("opposing_event_ids") or []),
        "opposing_evidence": list(reasoning.get("opposing_evidence") or []),
        "market_context": list(reasoning.get("market_context") or []),
        "partial_exit_weights": (
            source_risk.get("target_rebased_weights")
            or source_risk.get("partial_exit_weights")
            or _configured_partial_tp_weights()
        ),
        "atr": source_risk.get("atr"),
    }
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


def _setup_diagnostic(strategy_id, data, regime):
    """Explain why a native generator returned no setup without changing its rules."""
    def candles(tf):
        return data.get(tf) or []

    def history(tf, minimum):
        count = len(candles(tf))
        return (f"INSUFFICIENT_HISTORY: {tf} has {count} candles; needs {minimum}.") if count < minimum else None

    def missing(name, value):
        return f"MISSING_DATA: {name} is unavailable." if not value else None

    checks = []
    if strategy_id == "trend_pullback":
        checks += [history("4h", 60), history("1h", 30)]
        if len(candles("1h")) >= 15 and _atr(candles("1h")) is None:
            checks.append("INVALID_DATA: 1h ATR cannot be calculated.")
        if len(candles("4h")) >= 29 and _adx(candles("4h")) is None:
            checks.append("INSUFFICIENT_HISTORY: 4h ADX needs at least 29 valid candles.")
        if len(candles("4h")) >= 60 and len(candles("1h")) >= 30 and _atr(candles("1h")) and _adx(candles("4h")) is not None:
            checks.append("CONDITION_NOT_MET: trend alignment, ADX>=18, EMA20 pullback/reclaim and EMA slope did not align.")
    elif strategy_id == "volatility_breakout":
        checks.append(history("1h", 45))
        if len(candles("1h")) >= 15 and _atr(candles("1h")) is None:
            checks.append("INVALID_DATA: 1h ATR cannot be calculated.")
        if len(candles("1h")) >= 45 and _atr(candles("1h")):
            checks.append("CONDITION_NOT_MET: 20-candle breakout, prior volatility compression and >=1.2x volume were not all present.")
    elif strategy_id == "mean_reversion":
        checks.append(history("15m", 25))
        if regime.get("label") != "RANGE":
            checks.append(f"REGIME_MISMATCH: mean reversion requires RANGE; current regime is {regime.get('label')}.")
        if len(candles("15m")) >= 25 and _atr(candles("15m")) and _bollinger(_series(candles("15m"))) and _rsi(_series(candles("15m"))) is not None:
            checks.append("CONDITION_NOT_MET: Bollinger outside-to-inside re-entry, RSI threshold and VWAP-side confirmation did not align.")
    elif strategy_id == "liquidation_cascade":
        checks.append(history("1h", 20))
        oi = data.get("open_interest") or []
        oi_times = data.get("open_interest_timestamps_ms") or []
        if len(oi) < 2:
            checks.append(f"MISSING_DATA: open_interest history has {len(oi)} points; at least 2 timestamped observations are required.")
        if len(oi_times) < 2:
            checks.append("MISSING_DATA: open_interest_timestamps_ms has fewer than 2 timestamps; a single OI snapshot cannot establish contraction.")
        if len(oi) >= 2 and len(oi_times) >= 2 and data.get("snapshot_timestamp_ms"):
            checks.append("CONDITION_NOT_MET: OI contraction <=-1.5%, 1H impulse and same-direction taker-flow/funding confirmation did not align.")
    elif strategy_id == "orderflow_momentum":
        if not isinstance(data.get("orderbook"), dict):
            checks.append("MISSING_DATA: live orderbook snapshot is unavailable.")
        if not data.get("recent_trades"):
            checks.append("MISSING_DATA: recent executed trades are unavailable.")
        if not data.get("snapshot_timestamp_ms"):
            checks.append("MISSING_DATA: snapshot timestamp is unavailable.")
        if data.get("orderbook") and data.get("recent_trades") and data.get("snapshot_timestamp_ms"):
            checks.append("CONDITION_NOT_MET: fresh book/trades, spread ceiling, imbalance and taker-delta/absorption confirmation did not align.")
    elif strategy_id == "relative_strength":
        checks.append(history("4h", 55))
        symbol = str(data.get("symbol") or "").upper()
        keys = ["ETH"] if symbol.startswith("BTC/") else ["BTC"] if symbol.startswith("ETH/") else ["BTC", "ETH"]
        universe = data.get("correlation_universe") or {}
        for key in keys:
            if len(universe.get(key) or []) < 55:
                checks.append(f"MISSING_DATA: correlation_universe[{key}] needs at least 55 aligned 4h candles.")
        if len(candles("4h")) >= 55 and all(len(universe.get(key) or []) >= 55 for key in keys):
            checks.append("CONDITION_NOT_MET: at least 48 aligned returns, valid beta and +/-2% beta-adjusted 12-bar residual alpha with EMA20 confirmation were not all present.")
    elif strategy_id == "smc":
        checks.append("NO_SMC_GEOMETRY: integrated SMC specialist world did not provide a valid directional entry/stop/three-target plan.")
    checks = [item for item in checks if item]
    if not checks:
        checks = ["CONDITION_NOT_MET: strategy-native pattern conditions were not satisfied."]
    # Prefer missing-data/history explanations over a generic pattern message.
    return checks[0] if len(checks) == 1 else " | ".join(checks)


class SevenStrategyLab:
    """Run six independent generators plus one integrated SMC setup generator."""

    def classify_regime(self, data):
        """Expose the same regime classifier used by analyze for scoped statistics."""
        return _regime(data)

    def analyze(self, data, smc_result=None, performance_by_strategy=None):
        """Run seven independent setup generators, one shared filter, one selector."""
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

        # Stage 1: each strategy only creates its own setup. No common risk,
        # edge, ranking, fee, or portfolio gate runs in these evaluators.
        generated = []
        results = []
        for strategy_id, evaluator in evaluators.items():
            try:
                candidate = evaluator()
                if candidate is None:
                    reason = _setup_diagnostic(strategy_id, data, regime)
                    status = (
                        "MISSING_DATA" if "MISSING_DATA:" in reason
                        else "INSUFFICIENT_HISTORY" if "INSUFFICIENT_HISTORY:" in reason
                        else "CONDITION_NOT_MET" if "CONDITION_NOT_MET:" in reason or "REGIME_MISMATCH:" in reason
                        else "NO_SETUP"
                    )
                    results.append({
                        "strategy_id": strategy_id,
                        "strategy": STRATEGY_NAMES[strategy_id],
                        "status": status,
                        "reason": reason,
                        "rejection_stage": "STRATEGY_GENERATOR",
                        "rejection_reasons": [reason],
                    })
                    continue
                candidate = dict(candidate)
                candidate["strategy_id"] = strategy_id
                candidate["strategy"] = STRATEGY_NAMES[strategy_id]
                candidate["status"] = "RAW_SETUP"
                candidate["regime_fit"] = round(_regime_fit(strategy_id, regime), 3)
                generated.append(candidate)
                results.append(candidate)
            except Exception as exc:
                results.append({
                    "strategy_id": strategy_id,
                    "strategy": STRATEGY_NAMES[strategy_id],
                    "status": "ERROR",
                    "reason": f"{type(exc).__name__}: {exc}",
                })

        # Stage 2: the only shared eligibility gate. All seven strategies
        # arrive here under identical rules. It owns geometry, stop-risk,
        # execution friction, and minimum net-RR checks.
        eligible = []
        for candidate in generated:
            direction = str(candidate.get("direction") or "").upper()
            try:
                entry = float(candidate.get("entry"))
                stop = float(candidate.get("stop_loss"))
                targets = [float(candidate.get(key)) for key in ("tp1", "tp2", "tp3")]
                finite = all(math.isfinite(value) and value > 0 for value in [entry, stop, *targets])
                geometry_ok = (
                    finite
                    and ((direction == "LONG" and stop < entry < targets[0] <= targets[1] <= targets[2])
                         or (direction == "SHORT" and targets[0] >= targets[1] >= targets[2] and targets[0] < entry < stop))
                )
            except (TypeError, ValueError, OverflowError):
                geometry_ok = False
            if not geometry_ok:
                candidate["status"] = "BLOCKED_COMMON_FILTER"
                candidate["rejection_stage"] = "COMMON_FILTER"
                candidate["rejection_reasons"] = ["INVALID_OR_INCONSISTENT_SETUP_GEOMETRY"]
                continue

            # Execution eligibility also belongs to this one shared gate.
            # Far LIMIT plans stay valid; an impossible-side LIMIT or stale/far
            # MARKET entry is rejected here for every strategy by identical rules.
            entry_type = str(candidate.get("entry_type") or "MARKET").upper()
            current_price = _current_price(data)
            execution_rejection = None
            if entry_type not in {"MARKET", "LIMIT"}:
                execution_rejection = "UNSUPPORTED_ENTRY_TYPE"
            elif current_price is not None:
                distance_pct = abs(entry - current_price) / current_price
                if entry_type == "MARKET":
                    max_market_distance = float(getattr(Config, "MAX_MARKET_ENTRY_DISTANCE_PERCENT", 0.003))
                    if distance_pct > max_market_distance:
                        execution_rejection = "MARKET_ENTRY_TOO_FAR"
                elif direction == "LONG" and entry >= current_price:
                    execution_rejection = "LONG_LIMIT_NOT_BELOW_MARKET"
                elif direction == "SHORT" and entry <= current_price:
                    execution_rejection = "SHORT_LIMIT_NOT_ABOVE_MARKET"
            if execution_rejection:
                candidate["status"] = "BLOCKED_COMMON_FILTER"
                candidate["rejection_stage"] = "COMMON_FILTER"
                candidate["rejection_reasons"] = [execution_rejection]
                continue

            validation = _risk_validate_candidate(candidate)
            candidate["risk_validation"] = {
                key: value for key, value in validation.items() if key != "risk_plan"
            }
            if not validation.get("eligible"):
                candidate["status"] = "BLOCKED_COMMON_FILTER"
                candidate["rejection_stage"] = "COMMON_FILTER"
                candidate["rejection_reasons"] = [
                    validation.get("reason") or "COMMON_RISK_FILTER_REJECTED"
                ]
                continue

            risk_plan = validation["risk_plan"] or {}
            candidate["risk_plan"] = risk_plan
            candidate["partial_exit_weights"] = (
                risk_plan.get("partial_exit_weights") or _configured_partial_tp_weights()
            )
            candidate["estimated_net_rr"] = validation.get("weighted_net_rr")
            candidate["status"] = "FILTERED_SETUP"
            eligible.append(candidate)

        # Stage 3: one deterministic authority selects exactly one complete
        # candidate. No strategy can bypass the common filter or win via an
        # unvalidated historical-performance promotion flag.
        def selection_key(item):
            net_rr = item.get("estimated_net_rr")
            try:
                net_rr = float(net_rr)
            except (TypeError, ValueError, OverflowError):
                net_rr = 0.0
            strength = float(item.get("strength") or 0.0)
            regime_fit = float(item.get("regime_fit") or 0.0)
            return (round(net_rr, 6), round(strength * regime_fit, 4), item["strategy_id"])

        selected = max(eligible, key=selection_key) if eligible else None
        for candidate in eligible:
            candidate["selected"] = candidate is selected
            if candidate is selected:
                candidate["status"] = "SELECTED"
            else:
                candidate["status"] = "FILTERED_NOT_SELECTED"
                candidate["rejection_stage"] = "SINGLE_DECISION"
                candidate["rejection_reasons"] = ["Another eligible setup ranked higher"]

        status_counts = {}
        rejection_stage_counts = {}
        diagnostic_rows = []
        for item in results:
            status = item.get("status", "UNKNOWN")
            status_counts[status] = status_counts.get(status, 0) + 1
            stage = item.get("rejection_stage")
            if stage:
                rejection_stage_counts[stage] = rejection_stage_counts.get(stage, 0) + 1
            diagnostic_rows.append({
                "strategy_id": item["strategy_id"],
                "status": status,
                "direction": item.get("direction"),
                "entry_type": item.get("entry_type"),
                "rejection_stage": stage,
                "rejection_reasons": list(item.get("rejection_reasons") or []),
                "selected": item is selected,
            })

        return {
            "version": 3,
            "symbol": data.get("symbol"),
            "pipeline": ["SEVEN_INDEPENDENT_GENERATORS", "ONE_COMMON_FILTER", "ONE_FINAL_DECISION"],
            "diagnostics": {
                "strategy_count": len(diagnostic_rows),
                "raw_setup_count": len(generated),
                "common_filter_passed_count": len(eligible),
                "candidate_count": len(generated),
                "validated_candidate_count": len(eligible),
                "selected_strategy_id": selected.get("strategy_id") if selected else None,
                "status_counts": status_counts,
                "rejection_stage_counts": rejection_stage_counts,
                "strategies": diagnostic_rows,
            },
            "regime": regime,
            "strategies": results,
            "candidate_count": len(generated),
            "validated_candidate_count": len(eligible),
            "selected": selected,
            "selection_method": "single_common_filter_then_net_rr_strength_regime_rank",
            "performance_status": "OBSERVATIONAL_ONLY_NOT_AN_ELIGIBILITY_GATE",
            "warning": (
                "Strategy-native setup rules remain inside each generator. All shared risk, "
                "execution-cost and minimum-net-RR checks run once in the common filter. "
                "Historical strategy performance is observational and does not suppress setup generation."
            ),
        }
