"""Independent seven-strategy analysis and selection for Atlas.

The lab is advisory: it never mutates the SMC result or sends exchange orders.
New strategy candidates are explicitly marked experimental until strategy-specific
backtests and outcome samples establish a reliable edge.
"""
from __future__ import annotations

import math
from statistics import median

from strategy_performance import evaluate_strategy_edge, rank_validated_candidate


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


def _rsi(values, period=14):
    if len(values) < period + 1:
        return None
    changes = [right - left for left, right in zip(values[-(period + 1):-1], values[-period:])]
    gains = sum(max(change, 0.0) for change in changes) / period
    losses = sum(max(-change, 0.0) for change in changes) / period
    if losses <= 0:
        return 100.0 if gains > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + gains / losses)


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
    if direction == "LONG":
        targets = [entry + risk * multiple for multiple in (1.25, 2.0, 3.0)]
    else:
        targets = [entry - risk * multiple for multiple in (1.25, 2.0, 3.0)]
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
        "target_model": "R_MULTIPLE",
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
    if None in (e20, e50, e1):
        return None
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
    strength = min(92.0, 65.0 + min(trend_separation * 5.0, 15.0) + max(0.0, 10.0 - pullback_distance * 8.0))
    plan = _valid_plan(direction, entry, stop, atr, h1, "trend_pullback", strength, entry_reference=_entry_reference(data))
    if plan:
        plan["reasons"] = ["4H EMA20/EMA50 trend alignment", "1H EMA20 pullback and candle reclaim"]
    return plan


def _volatility_breakout(data):
    candles = data.get("1h") or []
    closes = _series(candles)
    atr = _atr(candles)
    if len(candles) < 30 or atr is None:
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
    if entry > max(prior_highs) and entry <= max(prior_highs) + atr and volume >= average_volume * 1.2:
        direction = "LONG"
        stop = entry - 1.5 * atr
    elif entry < min(prior_lows) and entry >= min(prior_lows) - atr and volume >= average_volume * 1.2:
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
        plan["reasons"] = ["1H 20-candle Donchian breakout", "Volume at least 1.2x prior 20-candle average"]
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
    if entry is None:
        return None
    middle = bands[1]
    if (direction == "LONG" and not lower <= entry <= middle) or (direction == "SHORT" and not middle <= entry <= upper):
        return None
    extremity = max(0.0, 42.0 - rsi) if direction == "LONG" else max(0.0, rsi - 58.0)
    strength = min(88.0, 65.0 + min(extremity * 0.5, 12.0) + min(abs(close - prev_close) / atr * 4.0, 8.0))
    plan = _valid_plan(direction, entry, stop, atr, candles, "mean_reversion", strength, entry_reference=_entry_reference(data))
    if plan:
        plan["reasons"] = ["15m Bollinger re-entry after outside close", f"RSI14={rsi:.1f}", "Range regime"]
    return plan


def _trade_flow(data):
    trades = data.get("recent_trades") or []
    buy = sell = 0.0
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        try:
            amount = float(trade.get("amount") or 0)
        except (TypeError, ValueError, OverflowError):
            continue
        if not math.isfinite(amount) or amount <= 0:
            continue
        side = str(trade.get("side") or "").lower()
        if side == "buy":
            buy += amount
        elif side == "sell":
            sell += amount
    total = buy + sell
    return (buy / total if total > 0 else None), total


def _orderflow_momentum(data):
    book = data.get("orderbook")
    candles = data.get("15m") or []
    atr = _atr(candles)
    if not isinstance(book, dict) or atr is None or not candles:
        return None
    bids, asks = book.get("bids") or [], book.get("asks") or []
    try:
        bid_qty = sum(float(level[1]) for level in bids[:10] if len(level) >= 2)
        ask_qty = sum(float(level[1]) for level in asks[:10] if len(level) >= 2)
    except (TypeError, ValueError, OverflowError):
        return None
    buy_ratio, total = _trade_flow(data)
    if bid_qty <= 0 or ask_qty <= 0 or buy_ratio is None or total <= 0:
        return None
    imbalance = bid_qty / ask_qty
    last = candles[-1]
    close, opened = _value(last, "close"), _value(last, "open")
    entry = _current_price(data)
    if close is None or opened is None or entry is None:
        return None
    direction = None
    if imbalance >= 1.25 and buy_ratio >= 0.58 and close > opened and entry >= opened:
        direction = "LONG"
        stop = entry - 1.5 * atr
    elif imbalance <= 0.80 and buy_ratio <= 0.42 and close < opened and entry <= opened:
        direction = "SHORT"
        stop = entry + 1.5 * atr
    else:
        return None
    strength = min(92.0, 65.0 + min(abs(imbalance - 1.0) * 20.0, 15.0) + min(abs(buy_ratio - 0.5) * 40.0, 10.0))
    plan = _valid_plan(direction, entry, stop, atr, candles, "orderflow_momentum", strength, entry_reference=_entry_reference(data))
    if plan:
        plan["reasons"] = [f"Top-10 order-book bid/ask quantity ratio={imbalance:.2f}", f"Recent taker buy ratio={buy_ratio:.2f}"]
        plan["data_quality"] = "LIVE_SNAPSHOT"
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
    oi_change = (current_oi - previous_oi) / previous_oi
    last = candles[-1]
    close, opened = _value(last, "close"), _value(last, "open")
    buy_ratio, _ = _trade_flow(data)
    entry = _current_price(data)
    if close is None or opened is None or entry is None:
        return None
    impulse = abs(close - opened) / atr
    direction = None
    if oi_change <= -0.015 and close > opened and entry > opened and impulse >= 1.0 and buy_ratio is not None and buy_ratio >= 0.56:
        direction = "LONG"
        stop = entry - 1.5 * atr
    elif oi_change <= -0.015 and close < opened and entry < opened and impulse >= 1.0 and buy_ratio is not None and buy_ratio <= 0.44:
        direction = "SHORT"
        stop = entry + 1.5 * atr
    else:
        return None
    strength = min(92.0, 65.0 + min(abs(oi_change) * 400.0, 15.0) + min(impulse * 5.0, 10.0))
    plan = _valid_plan(direction, entry, stop, atr, candles, "liquidation_cascade", strength, entry_reference=_entry_reference(data))
    if plan:
        plan["reasons"] = [f"Open interest contraction={oi_change * 100:.2f}%", f"1H impulse={impulse:.2f} ATR", "Trade-flow confirmation"]
        plan["data_quality"] = "OI_CONTRACTION_PROXY_NOT_EXCHANGE_LIQUIDATION_FEED"
    return plan


def _relative_strength(data):
    candles = data.get("4h") or []
    closes = _series(candles)
    atr = _atr(candles)
    if len(closes) < 15 or atr is None:
        return None
    benchmark = "ETH" if str(data.get("symbol") or "").upper().startswith("BTC/") else "BTC"
    universe = data.get("correlation_universe") or {}
    benchmark_candles = universe.get(benchmark) or []
    benchmark_closes = _series(benchmark_candles)
    if len(benchmark_closes) < 15:
        return None
    own_return = closes[-1] / closes[-13] - 1.0
    benchmark_return = benchmark_closes[-1] / benchmark_closes[-13] - 1.0
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
