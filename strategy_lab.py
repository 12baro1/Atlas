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
from decision_engine import DecisionEngine
from config import Config
from shared.market_structure_services import (trend_structure, displacement, volatility_regime, breakout_acceptance, statistical_deviation, rsi_divergence)
from strategies.smc.submotors import dealing_range, liquidity_draw, poi_freshness, breaker_validation, reclaim_acceptance, inducement_proxy, narrative as smc_narrative
from shared.microstructure_services import cumulative_volume_delta, liquidation_events, beta_stability, relative_volume
from strategies.orderflow.analytics import build_footprint, liquidity_walls, build_orderflow_evidence
from shared.analysis_context import analysis_scope, cached_analysis
from shared.analysis_services import (
    _value, _valid_ohlc, _series, _ema, _atr, _adx, _candle_quality,
    _relative_volume, _directional_movement, _efficiency_ratio, _rsi,
    _vwap, _bollinger,
)

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


def _valid_plan(direction, entry, stop, atr, candles, source, strength, entry_type="MARKET", entry_reference="LAST_CLOSED_15M_FALLBACK", structure_candles=None):
    if direction not in {"LONG", "SHORT"} or not all(
        isinstance(value, (int, float)) and math.isfinite(value) and value > 0
        for value in (entry, stop, atr)
    ):
        return None
    # The strategy-provided stop is only a directional sanity check. Its
    # numeric level is never used; the shared structure engine replaces it.
    if (direction == "LONG" and stop >= entry) or (direction == "SHORT" and stop <= entry):
        return None

    # Detect pivots independently per timeframe. Never concatenate candle
    # intervals: cross-timeframe concatenation would create false pivots.
    candle_sets = structure_candles or [candles]
    swing_highs, swing_lows = [], []
    for candle_set in candle_sets:
        sample = list(candle_set or [])[-120:]
        # Invalid OHLC data must never manufacture a structural stop or target.
        if any(not _valid_ohlc(item) for item in sample):
            return None
        for index in range(2, len(sample) - 2):
            high = _value(sample[index], "high")
            low = _value(sample[index], "low")
            if high is None or low is None:
                continue
            left_highs = [_value(item, "high") for item in sample[index - 2:index]]
            right_highs = [_value(item, "high") for item in sample[index + 1:index + 3]]
            left_lows = [_value(item, "low") for item in sample[index - 2:index]]
            right_lows = [_value(item, "low") for item in sample[index + 1:index + 3]]
            if all(value is not None for value in left_highs + right_highs):
                if high > max(left_highs + right_highs):
                    swing_highs.append(high)
            if all(value is not None for value in left_lows + right_lows):
                if low < min(left_lows + right_lows):
                    swing_lows.append(low)

    # Stop invalidation comes from the nearest confirmed opposing swing;
    # ATR contributes only a small buffer around that structural level.
    buffer = atr * 0.05
    if direction == "LONG":
        invalidation = [value for value in swing_lows if value < entry]
        if not invalidation:
            return None
        structural_stop = max(invalidation) - buffer
    else:
        invalidation = [value for value in swing_highs if value > entry]
        if not invalidation:
            return None
        structural_stop = min(invalidation) + buffer

    risk_distance = entry - structural_stop if direction == "LONG" else structural_stop - entry
    if risk_distance <= 0:
        return None

    if direction == "LONG":
        structural_targets = sorted(set(
            value for value in swing_highs
            if value > entry and (value - entry) / risk_distance >= 1.25
        ))
    else:
        structural_targets = sorted(set(
            value for value in swing_lows
            if value < entry and (entry - value) / risk_distance >= 1.25
        ), reverse=True)

    # Never fabricate 2R/3R/4R targets. Without three actual opposing
    # swing-liquidity levels this strategy has no executable geometry.
    if len(structural_targets) < 3:
        return None
    targets = structural_targets[:3]
    rr_values = [abs(value - entry) / risk_distance for value in targets]
    plan = {
        "status": "CANDIDATE", "strategy_id": source, "strategy": STRATEGY_NAMES[source],
        "direction": direction, "entry_type": str(entry_type or "MARKET").upper(),
        "entry_reference": entry_reference, "entry": round(entry, 10), "atr": round(atr, 10),
        "stop_loss": round(structural_stop, 10), "tp1": round(targets[0], 10),
        "tp2": round(targets[1], 10), "tp3": round(targets[2], 10),
        "rr_tp1": round(rr_values[0], 4), "rr_tp2": round(rr_values[1], 4),
        "rr_tp3": round(rr_values[2], 4), "strength": round(float(strength), 2),
        "stop_model": "CONFIRMED_SWING_INVALIDATION_ATR_BUFFER",
        "target_model": "CONFIRMED_OPPOSING_SWING_LIQUIDITY",
        "experimental": source != "smc", "reasons": [],
    }
    # Shared risk, fees, minimum-RR and execution gates run after generation.
    plan["partial_exit_weights"] = _configured_partial_tp_weights()
    return plan

@cached_analysis
def _current_price(data):
    try:
        value = float(data.get("current_price"))
    except (TypeError, ValueError, OverflowError):
        value = None
    if value is not None and math.isfinite(value) and value > 0:
        return value
    candles = data.get("15m") or []
    return _value(candles[-1], "close") if candles else None


@cached_analysis
def _entry_reference(data):
    return str(data.get("current_price_source") or "LAST_CLOSED_15M_FALLBACK")


@cached_analysis
def _structure_candle_sets(data):
    """Return available OHLCV series separately, preserving timeframe identity."""
    return [
        data.get(timeframe) or []
        for timeframe in ("15m", "1h", "4h", "1d", "1w")
        if data.get(timeframe)
    ]


@cached_analysis
def _regime(data):
    candles = data.get("4h") or []
    closes = _series(candles)
    atr = _atr(candles)
    fast, slow = _ema(closes, 20), _ema(closes, 50)
    adx_value = _adx(candles)
    efficiency = _efficiency_ratio(closes, 20)
    if None in (atr, fast, slow, adx_value, efficiency) or not closes:
        return {"label": "UNKNOWN", "trend": "NEUTRAL", "strength": 0.0}
    distance = abs(fast - slow) / atr
    trend = "BULLISH" if fast > slow else "BEARISH" if fast < slow else "NEUTRAL"
    # EMA separation alone confuses directional trends with noisy, high-beta chop.
    if distance >= 0.65 and adx_value >= 18.0 and efficiency >= 0.25:
        label = "TREND"
    elif distance <= 0.65 and adx_value < 22.0 and efficiency <= 0.35:
        label = "RANGE"
    else:
        label = "TRANSITION"
    # A high-volatility flag requires relative ATR expansion, not a fixed coin price threshold.
    atr_percentages = []
    for end in range(max(15, len(candles) - 80), len(candles) + 1):
        sample = candles[:end]
        sample_atr = _atr(sample)
        close = _value(sample[-1], "close") if sample else None
        if sample_atr and close and close > 0:
            atr_percentages.append(sample_atr / close)
    if len(atr_percentages) >= 10 and atr_percentages[-1] > median(atr_percentages[:-1]) * 1.5:
        label = "HIGH_VOLATILITY"
    return {
        "label": label, "trend": trend, "strength": round(distance, 3),
        "adx": round(adx_value, 2), "efficiency_ratio": round(efficiency, 3),
        "atr_pct": round(atr / closes[-1], 6) if closes[-1] > 0 else None,
    }


def _trend_pullback(data):
    from strategies.trend import generate
    return generate(data)
def _volatility_breakout(data):
    from strategies.breakout import generate
    return generate(data)
def _mean_reversion(data, regime):
    from strategies.mean_reversion import generate
    return generate(data, regime)
@cached_analysis
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
    from strategies.orderflow.strategy import generate
    return generate(data)

def _liquidation_cascade(data):
    from strategies.liquidation.strategy import generate
    return generate(data)

def _relative_strength(data):
    from strategies.relative_strength.strategy import generate
    return generate(data)

@cached_analysis
def _absorption_proxy(flow, candle, atr):
    from strategies.orderflow.strategy import _absorption_proxy as infer_absorption
    return infer_absorption(flow, candle, atr)



def _smc_candidate(result, data=None):
    from strategies.smc.strategy import generate
    return generate(result, data)

def _regime_fit(strategy_id, regime):
    label, trend = regime.get("label"), regime.get("trend")
    preferred = {
        "trend_pullback": {"TREND": 1.0, "TRANSITION": 0.55},
        "volatility_breakout": {"HIGH_VOLATILITY": 1.0, "TREND": 0.85, "TRANSITION": 0.70},
        "mean_reversion": {"RANGE": 1.0, "TRANSITION": 0.45},
        "liquidation_cascade": {"HIGH_VOLATILITY": 1.0, "TRANSITION": 0.70},
        "orderflow_momentum": {"TREND": 0.9, "HIGH_VOLATILITY": 1.0, "TRANSITION": 0.70},
        "relative_strength": {"TREND": 0.9, "HIGH_VOLATILITY": 0.75, "TRANSITION": 0.60},
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
            checks.append("CONDITION_NOT_MET: 4H EMA trend, ADX/DMI direction, 1H EMA20 pullback, reclaim candle body/close-location and directional efficiency did not align.")
    elif strategy_id == "volatility_breakout":
        checks.append(history("1h", 45))
        if len(candles("1h")) >= 15 and _atr(candles("1h")) is None:
            checks.append("INVALID_DATA: 1h ATR cannot be calculated.")
        if len(candles("1h")) >= 45 and _atr(candles("1h")):
            checks.append("CONDITION_NOT_MET: 20-candle close breakout, lower-quartile bandwidth compression, >=1.30x median relative volume and decisive breakout candle anatomy were not all present.")
    elif strategy_id == "mean_reversion":
        checks.append(history("15m", 25))
        if regime.get("label") != "RANGE":
            checks.append(f"REGIME_MISMATCH: mean reversion requires RANGE; current regime is {regime.get('label')}.")
        if len(candles("15m")) >= 25 and _atr(candles("15m")) and _bollinger(_series(candles("15m"))) and _rsi(_series(candles("15m"))) is not None:
            checks.append("CONDITION_NOT_MET: Bollinger re-entry, RSI reversal slope, rejection wick/close-location and VWAP-side confirmation did not align.")
    elif strategy_id == "liquidation_cascade":
        checks.append(history("1h", 21))
        oi = data.get("open_interest") or []
        oi_times = data.get("open_interest_timestamps_ms") or []
        if len(oi) < 2:
            checks.append(f"MISSING_DATA: open_interest history has {len(oi)} points; at least 2 timestamped observations are required.")
        if len(oi_times) < 2:
            checks.append("MISSING_DATA: open_interest_timestamps_ms has fewer than 2 timestamps; a single OI snapshot cannot establish contraction.")
        if len(oi) >= 2 and len(oi_times) >= 2 and data.get("snapshot_timestamp_ms"):
            checks.append("CONDITION_NOT_MET: timestamped OI contraction <=-1.5%, >=1.0 ATR impulse, >=1.25x relative volume, directional candle close, taker-flow and funding context did not align.")
    elif strategy_id == "orderflow_momentum":
        if not isinstance(data.get("orderbook"), dict):
            checks.append("MISSING_DATA: live orderbook snapshot is unavailable.")
        if not data.get("recent_trades"):
            checks.append("MISSING_DATA: recent executed trades are unavailable.")
        if not data.get("snapshot_timestamp_ms"):
            checks.append("MISSING_DATA: snapshot timestamp is unavailable.")
        if data.get("orderbook") and data.get("recent_trades") and data.get("snapshot_timestamp_ms"):
            checks.append("CONDITION_NOT_MET: fresh book/trades, at least 20 valid trades, spread ceiling, depth-weighted imbalance, taker delta and momentum-candle or absorption confirmation did not align.")
    elif strategy_id == "relative_strength":
        checks.append(history("4h", 55))
        symbol = str(data.get("symbol") or "").upper()
        keys = ["ETH"] if symbol.startswith("BTC/") else ["BTC"] if symbol.startswith("ETH/") else ["BTC", "ETH"]
        universe = data.get("correlation_universe") or {}
        for key in keys:
            if len(universe.get(key) or []) < 55:
                checks.append(f"MISSING_DATA: correlation_universe[{key}] needs at least 55 aligned 4h candles.")
        if len(candles("4h")) >= 55 and all(len(universe.get(key) or []) >= 55 for key in keys):
            checks.append("CONDITION_NOT_MET: 48 aligned returns, stable beta, volatility-scaled 12-bar residual alpha, same-direction recent 6-bar alpha and rising/falling EMA20 confirmation were not all present.")
    elif strategy_id == "smc":
        checks.append("NO_SMC_GEOMETRY: integrated SMC specialist world did not provide a valid directional entry/stop/three-target plan.")
    checks = [item for item in checks if item]
    if not checks:
        checks = ["CONDITION_NOT_MET: strategy-native pattern conditions were not satisfied."]
    # Prefer missing-data/history explanations over a generic pattern message.
    return checks[0] if len(checks) == 1 else " | ".join(checks)


class SevenStrategyLab:
    """Run six independent generators plus one integrated SMC setup generator."""

    def __init__(self, decision_engine=None):
        # The main engine injects its one decision authority. Standalone use
        # remains supported for strategy-lab tests and research tooling.
        self.decision_engine = decision_engine or DecisionEngine()

    @analysis_scope
    def classify_regime(self, data):
        """Expose the same regime classifier used by analyze for scoped statistics."""
        return _regime(data)

    @analysis_scope
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
            "smc": lambda: _smc_candidate(smc_result, data),
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
        selected = self.decision_engine.select_strategy_candidate(eligible)
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
                "reason": item.get("reason"),
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
