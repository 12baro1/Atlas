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
from trace_context import ensure_trace, record_stage, trace_id
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


def _raw_candidate(direction, entry, stop, atr, source, strength, entry_type="MARKET", entry_reference="LAST_CLOSED_15M_FALLBACK"):
    """Create a strategy-native raw setup without applying shared geometry gates.

    Strategy packages own pattern detection and preferred entry/initial invalidation.
    Confirmed structural stop/targets are finalized later by the one common filter.
    """
    try:
        values = [float(entry), float(stop), float(atr), float(strength)]
    except (TypeError, ValueError, OverflowError):
        return None
    entry_value, initial_stop, atr_value, strength_value = values
    if direction not in {"LONG", "SHORT"} or not all(
        math.isfinite(value) and value > 0 for value in (entry_value, initial_stop, atr_value)
    ) or not math.isfinite(strength_value):
        return None
    if (direction == "LONG" and initial_stop >= entry_value) or (
        direction == "SHORT" and initial_stop <= entry_value
    ):
        return None
    return {
        "status": "RAW_SETUP",
        "strategy_id": source,
        "strategy": STRATEGY_NAMES[source],
        "direction": direction,
        "entry_type": str(entry_type or "MARKET").upper(),
        "entry_reference": entry_reference,
        "entry": round(entry_value, 10),
        "initial_stop_loss": round(initial_stop, 10),
        "atr": round(atr_value, 10),
        "strength": round(strength_value, 2),
        "experimental": source != "smc",
        "reasons": [],
        "partial_exit_weights": _configured_partial_tp_weights(),
    }


def _finalize_candidate_geometry(candidate, candle_sets):
    """Apply shared swing invalidation and real-liquidity targets after generation.

    Returns a rejection reason, or None after mutating the candidate with its
    final stop and three confirmed opposing swing targets.
    """
    if not isinstance(candidate, dict):
        return "INVALID_RAW_CANDIDATE"
    direction = str(candidate.get("direction") or "").upper()
    try:
        entry = float(candidate.get("entry"))
        initial_stop = float(candidate.get("initial_stop_loss", candidate.get("stop_loss")))
        atr = float(candidate.get("atr"))
    except (TypeError, ValueError, OverflowError):
        return "INVALID_RAW_GEOMETRY_INPUT"
    if direction not in {"LONG", "SHORT"} or not all(
        math.isfinite(value) and value > 0 for value in (entry, initial_stop, atr)
    ):
        return "INVALID_RAW_GEOMETRY_INPUT"
    if (direction == "LONG" and initial_stop >= entry) or (
        direction == "SHORT" and initial_stop <= entry
    ):
        return "INVALID_INITIAL_STOP_DIRECTION"

    # Detect pivots independently per timeframe; never concatenate intervals.
    swing_highs, swing_lows = [], []
    for candle_set in candle_sets or []:
        sample = list(candle_set or [])[-120:]
        if any(not _valid_ohlc(item) for item in sample):
            return "INVALID_OHLC_IN_STRUCTURE_DATA"
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

    buffer = atr * 0.05
    if direction == "LONG":
        invalidation = [value for value in swing_lows if value < entry]
        if not invalidation:
            return "NO_CONFIRMED_STOP_INVALIDATION"
        structural_stop = max(invalidation) - buffer
    else:
        invalidation = [value for value in swing_highs if value > entry]
        if not invalidation:
            return "NO_CONFIRMED_STOP_INVALIDATION"
        structural_stop = min(invalidation) + buffer

    risk_distance = entry - structural_stop if direction == "LONG" else structural_stop - entry
    if not math.isfinite(risk_distance) or risk_distance <= 0:
        return "INVALID_STRUCTURAL_STOP_DISTANCE"

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

    if len(structural_targets) < 3:
        return f"INSUFFICIENT_OPPOSING_SWING_TARGETS:{len(structural_targets)}/3"
    targets = structural_targets[:3]
    rr_values = [abs(value - entry) / risk_distance for value in targets]
    candidate.update({
        "stop_loss": round(structural_stop, 10),
        "tp1": round(targets[0], 10),
        "tp2": round(targets[1], 10),
        "tp3": round(targets[2], 10),
        "rr_tp1": round(rr_values[0], 4),
        "rr_tp2": round(rr_values[1], 4),
        "rr_tp3": round(rr_values[2], 4),
        "stop_model": "CONFIRMED_SWING_INVALIDATION_ATR_BUFFER",
        "target_model": "CONFIRMED_OPPOSING_SWING_LIQUIDITY",
        "geometry_finalized_by": "COMMON_FILTER",
    })
    candidate.pop("initial_stop_loss", None)
    return None


def _valid_plan(direction, entry, stop, atr, candles, source, strength, entry_type="MARKET", entry_reference="LAST_CLOSED_15M_FALLBACK", structure_candles=None):
    """Compatibility helper for research/tests; live generators use raw candidates."""
    candidate = _raw_candidate(
        direction, entry, stop, atr, source, strength,
        entry_type=entry_type, entry_reference=entry_reference,
    )
    if candidate is None:
        return None
    reason = _finalize_candidate_geometry(
        candidate, structure_candles or [candles],
    )
    return None if reason else candidate


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


# Strateji başına veri kullanım raporu upstream `_STRATEGY_INPUT_FIELDS`
# eşlemesiyle üretilir; yalnızca stratejinin gerçekten okuduğu alanlar raporlanır.
_SETUP_PRODUCED_STATUSES = {
    "RAW_SETUP", "FILTERED_SETUP", "SELECTED", "FILTERED_NOT_SELECTED", "BLOCKED_COMMON_FILTER",
}


def _setup_produced(status):
    return status in _SETUP_PRODUCED_STATUSES


def _common_filter_result(status):
    if status in {"SELECTED", "FILTERED_NOT_SELECTED"}:
        return "PASSED"
    if status == "BLOCKED_COMMON_FILTER":
        return "REJECTED"
    return "NOT_REACHED"


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
        aligned_pairs = sum(1 for stamp, value in zip(oi_times, oi) if stamp is not None and value is not None)
        if len(oi) < 2 or len(oi_times) < 2 or aligned_pairs < 2:
            # Tek anlık OI snapshot'ı tarihsel değişim kuramaz; açıkça raporlanır.
            checks.append(
                "MISSING_DATA: INSUFFICIENT_OI_HISTORY - "
                f"open_interest has {len(oi)} value(s) with open_interest_timestamps_ms aligned to {aligned_pairs} "
                "timestamped observation(s); at least 2 timestamped observations are required. "
                "A single OI snapshot cannot establish contraction."
            )
        elif len(oi) >= 2 and len(oi_times) >= 2 and data.get("snapshot_timestamp_ms"):
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


_STRATEGY_ANALYSIS_FEATURES = {
    "trend_pullback": (
        "4H EMA20/EMA50, Wilder ADX/DMI and directional efficiency",
        "1H EMA20 pullback/reclaim, ATR and candle structure",
    ),
    "volatility_breakout": (
        "1H Bollinger bandwidth compression and 20-bar close acceptance",
        "Relative volume, ATR and breakout candle anatomy",
    ),
    "mean_reversion": (
        "15m Bollinger re-entry, RSI reversal slope and VWAP deviation",
        "Range-regime and rejection-wick confirmation",
    ),
    "liquidation_cascade": (
        "Timestamped OI contraction, 1H ATR impulse and relative volume",
        "Recent taker flow and fresh funding context",
        "Real exchange liquidation events as optional directional confluence",
    ),
    "orderflow_momentum": (
        "Fresh L2 order-book imbalance, spread and recent taker trades",
        "Executed footprint and fresh timestamped CVD",
        "Opposing displayed liquidity wall and real liquidation pressure",
        "15m candle anatomy and absorption proxy (not direct passive-fill observation)",
    ),
    "relative_strength": (
        "Aligned 4H returns versus BTC/ETH benchmarks",
        "Configured sector-peer returns, rolling beta stability and residual alpha",
    ),
    "smc": (
        "Closed multi-timeframe market structure and liquidity evidence",
        "SMC-owned specialist submotors for OB/FVG/OTE, breakers and reclaim narrative",
    ),
}


_STRATEGY_INPUT_FIELDS = {
    "trend_pullback": ("4h", "1h", "current_price"),
    "volatility_breakout": ("1h", "current_price"),
    "mean_reversion": ("15m", "current_price"),
    "liquidation_cascade": ("1h", "open_interest", "open_interest_timestamps_ms",
                            "recent_trades", "funding_rate", "liquidation_events"),
    "orderflow_momentum": ("15m", "orderbook", "orderbook_timestamp_ms",
                           "recent_trades", "recent_trades_timestamp_ms",
                           "trade_flow_history", "liquidation_events"),
    "relative_strength": ("4h", "correlation_universe", "sector_peer_universe"),
    "smc": ("15m", "1h", "4h", "1d", "1w", "smt_universe"),
}


def _strategy_data_usage(strategy_id, data, smc_result=None):
    """Expose actual generator input availability without imposing shared gates."""
    fields = _STRATEGY_INPUT_FIELDS.get(strategy_id, ())
    inputs = {}
    minimum_candles = {
        "trend_pullback": {"4h": 60, "1h": 30},
        "volatility_breakout": {"1h": 45},
        "mean_reversion": {"15m": 25},
        "liquidation_cascade": {"1h": 21},
        "orderflow_momentum": {"15m": 15},
        "relative_strength": {"4h": 55},
        "smc": {"15m": 1, "1h": 1, "4h": 1, "1d": 1, "1w": 1},
    }.get(strategy_id, {})
    shared_snapshot = data.get("shared_market_evidence") or {}
    shared_sources = shared_snapshot.get("sources") or {}
    symbol = str(data.get("symbol") or "").upper()
    benchmark_keys = (
        ["ETH"] if symbol.startswith("BTC/") else
        ["BTC"] if symbol.startswith("ETH/") else ["BTC", "ETH"]
    )
    for field in fields:
        value = data.get(field)
        if field in minimum_candles:
            available = len(value or []) >= minimum_candles[field]
            status = "AVAILABLE" if available else "INSUFFICIENT_HISTORY"
        elif field == "current_price":
            # _current_price falls back to the last fully closed 15m candle.
            available = value is not None or bool(data.get("15m"))
            status = "AVAILABLE" if available else "UNAVAILABLE"
        elif field == "orderbook":
            source_state = (shared_sources.get("orderbook") or {}).get("state")
            available = (
                source_state == "FRESH" if source_state is not None
                else isinstance(value, dict) and bool(value.get("bids")) and bool(value.get("asks"))
            )
            status = "AVAILABLE" if available else source_state or "UNAVAILABLE"
        elif field == "open_interest":
            oi_evidence = shared_snapshot.get("open_interest") or {}
            available = (
                oi_evidence.get("state") == "FRESH" and int(oi_evidence.get("count") or 0) >= 2
                if shared_snapshot else len(value or []) >= 2
            )
            status = (
                "AVAILABLE" if available else
                "INSUFFICIENT_HISTORY" if int(oi_evidence.get("count") or len(value or [])) < 2
                else oi_evidence.get("state") or "INSUFFICIENT_HISTORY"
            )
        elif field == "open_interest_timestamps_ms":
            available = len(value or []) >= 2
            status = "AVAILABLE" if available else "INSUFFICIENT_HISTORY"
        elif field == "recent_trades":
            trade_evidence = shared_snapshot.get("trades") or {}
            valid_count = int(trade_evidence.get("trade_count") or 0)
            available = (
                trade_evidence.get("state") == "FRESH" and valid_count >= 20
                if shared_snapshot else len(value or []) >= 20
            )
            status = (
                "AVAILABLE" if available else
                "INSUFFICIENT_DATA" if valid_count < 20
                else trade_evidence.get("state") or "INSUFFICIENT_DATA"
            )
        elif field == "funding_rate":
            funding_evidence = shared_snapshot.get("funding") or {}
            available = (
                funding_evidence.get("state") == "FRESH"
                if shared_snapshot and value else bool(value)
            )
            status = "AVAILABLE" if available else funding_evidence.get("state") or "UNAVAILABLE"
        elif field.endswith("_timestamps_ms"):
            available = bool(value)
            status = "AVAILABLE" if available else "UNAVAILABLE"
        elif field == "correlation_universe":
            has_universe = isinstance(value, dict) and bool(value)
            available = has_universe and all(
                len(value.get(key) or []) >= 55 for key in benchmark_keys
            )
            status = (
                "AVAILABLE" if available else
                "INSUFFICIENT_HISTORY" if has_universe else "UNAVAILABLE"
            )
        elif field == "sector_peer_universe":
            available = isinstance(value, dict) and bool(value)
            status = "AVAILABLE" if available else "OPTIONAL_UNAVAILABLE"
        elif field in {"smt_universe"}:
            available = isinstance(value, dict) and bool(value)
            status = "AVAILABLE" if available else "OPTIONAL_UNAVAILABLE"
        else:
            available = bool(value)
            status = "AVAILABLE" if available else "UNAVAILABLE"
        inputs[field] = status
    if strategy_id == "smc":
        inputs["smc_specialist_result"] = (
            "AVAILABLE" if isinstance(smc_result, dict) and smc_result else "UNAVAILABLE"
        )
    shared = data.get("shared_market_evidence") or {}
    sources = shared.get("sources") or {}
    relevant_sources = {
        key: value for key, value in sources.items()
        if key in {
            "ohlcv", "orderbook", "trades", "cvd", "liquidations",
            "open_interest", "funding",
        }
    }
    return {
        "generator_inputs": inputs,
        "analysis_features": list(_STRATEGY_ANALYSIS_FEATURES.get(strategy_id, ())),
        "shared_source_status": relevant_sources,
        "note": "Availability/provenance diagnostics; strategies retain independent setup rules.",
    }


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
        ensure_trace(data)
        if not isinstance(data.get("shared_market_evidence"), dict):
            from shared.market_data_services import build_shared_market_evidence
            data = dict(data)
            data["shared_market_evidence"] = build_shared_market_evidence(data)
        regime = _regime(data)
        record_stage(
            data,
            "SHARED_MARKET_EVIDENCE",
            timestamp_ms=data.get("snapshot_timestamp_ms"),
            source="SHARED_ANALYSIS_SERVICES",
            freshness="UNKNOWN",
            availability="AVAILABLE",
            detail={
                "regime": regime.get("label"),
                "regime_trend": regime.get("trend"),
                "note": "Shared services produce market evidence only; strategy decisions stay in each generator.",
            },
        )
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
                        "data_usage": _strategy_data_usage(strategy_id, data, smc_result),
                    })
                    record_stage(
                        data,
                        "STRATEGY_SETUP",
                        timestamp_ms=data.get("snapshot_timestamp_ms"),
                        source=f"STRATEGY:{strategy_id}",
                        freshness="UNKNOWN",
                        availability="UNAVAILABLE",
                        reason=reason,
                        strategy=strategy_id,
                        filter_result="NOT_REACHED",
                        decision=None,
                    )
                    continue
                candidate = dict(candidate)
                candidate["strategy_id"] = strategy_id
                candidate["strategy"] = STRATEGY_NAMES[strategy_id]
                candidate["status"] = "RAW_SETUP"
                # Gözlemlenebilirlik: adayın kurulum kimliği (aynı analizde benzersiz).
                candidate["setup_id"] = "setup-{}-{:02d}".format(strategy_id, len(generated) + 1)
                candidate["regime_fit"] = round(_regime_fit(strategy_id, regime), 3)
                candidate["data_usage"] = _strategy_data_usage(strategy_id, data, smc_result)
                generated.append(candidate)
                results.append(candidate)
                record_stage(
                    data,
                    "STRATEGY_SETUP",
                    timestamp_ms=data.get("snapshot_timestamp_ms"),
                    source=f"STRATEGY:{strategy_id}",
                    freshness="UNKNOWN",
                    availability="AVAILABLE",
                    strategy=strategy_id,
                    setup_id=candidate["setup_id"],
                    detail={"direction": candidate.get("direction"), "entry_type": candidate.get("entry_type")},
                )
            except Exception as exc:
                results.append({
                    "strategy_id": strategy_id,
                    "strategy": STRATEGY_NAMES[strategy_id],
                    "status": "ERROR",
                    "reason": f"{type(exc).__name__}: {exc}",
                    "data_usage": _strategy_data_usage(strategy_id, data, smc_result),
                })
                record_stage(
                    data,
                    "STRATEGY_SETUP",
                    timestamp_ms=data.get("snapshot_timestamp_ms"),
                    source=f"STRATEGY:{strategy_id}",
                    freshness="UNKNOWN",
                    availability="ERROR",
                    reason=f"{type(exc).__name__}: {exc}",
                    strategy=strategy_id,
                    filter_result="NOT_REACHED",
                )

        # Stage 2: the only shared eligibility gate. All seven strategies
        # arrive here under identical rules. It owns geometry, stop-risk,
        # execution friction, and minimum net-RR checks.
        def _record_common_filter(candidate, filter_result, reason=None):
            # Gözlemlenebilirlik: her adayın ortak filtre sonucu trace'e yazılır.
            record_stage(
                data,
                "COMMON_FILTER",
                timestamp_ms=data.get("snapshot_timestamp_ms"),
                source="COMMON_FILTER",
                freshness="UNKNOWN",
                availability="AVAILABLE" if filter_result == "PASSED" else "REJECTED",
                reason=reason,
                strategy=candidate.get("strategy_id"),
                setup_id=candidate.get("setup_id"),
                filter_result=filter_result,
                decision=None,
            )

        eligible = []
        for candidate in generated:
            # Non-SMC strategies publish their raw pattern setup first. Shared
            # structural stop/TP geometry is applied here, never inside a strategy.
            if candidate.get("strategy_id") != "smc" and not all(
                candidate.get(key) is not None for key in ("stop_loss", "tp1", "tp2", "tp3")
            ):
                geometry_reason = _finalize_candidate_geometry(
                    candidate, _structure_candle_sets(data),
                )
                if geometry_reason:
                    candidate["status"] = "BLOCKED_COMMON_FILTER"
                    candidate["rejection_stage"] = "COMMON_FILTER"
                    candidate["rejection_reasons"] = [geometry_reason]
                    _record_common_filter(candidate, "REJECTED", geometry_reason)
                    continue

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
                _record_common_filter(candidate, "REJECTED", "INVALID_OR_INCONSISTENT_SETUP_GEOMETRY")
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
                _record_common_filter(candidate, "REJECTED", execution_rejection)
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
                _record_common_filter(
                    candidate, "REJECTED",
                    validation.get("reason") or "COMMON_RISK_FILTER_REJECTED",
                )
                continue

            risk_plan = validation["risk_plan"] or {}
            candidate["risk_plan"] = risk_plan
            candidate["partial_exit_weights"] = (
                risk_plan.get("partial_exit_weights") or _configured_partial_tp_weights()
            )
            candidate["estimated_net_rr"] = validation.get("weighted_net_rr")
            candidate["status"] = "FILTERED_SETUP"
            eligible.append(candidate)
            _record_common_filter(candidate, "PASSED")

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

        # Veri kullanım raporu: yalnızca gözlemlenebilirlik. Seçim bittikten
        # sonra, her stratejinin NİHAİ durumu, jeneratör girdi durumu ve ortak
        # filtre sonucu birleştirilir; karar mantığını etkilemez.
        data_usage = []
        for item in results:
            status = item.get("status")
            usage = item.get("data_usage") or {}
            row = {
                "strategy_id": item["strategy_id"],
                "strategy": item.get("strategy") or STRATEGY_NAMES[item["strategy_id"]],
                "status": status,
                "setup_produced": _setup_produced(status),
                "common_filter_result": _common_filter_result(status),
                "trace_id": trace_id(data),
                "generator_inputs": dict(usage.get("generator_inputs") or {}),
                "analysis_features": list(usage.get("analysis_features") or []),
                "shared_source_status": dict(usage.get("shared_source_status") or {}),
            }
            if status == "BLOCKED_COMMON_FILTER":
                row["filter_reasons"] = list(item.get("rejection_reasons") or [])
            elif status == "FILTERED_NOT_SELECTED":
                row["filter_reasons"] = [
                    "SINGLE_DECISION: " + " ".join(item.get("rejection_reasons") or [])
                ]
            else:
                row["filter_reasons"] = []
            if row["setup_produced"]:
                row["missing_reason"] = None
            else:
                reasons = [item.get("reason")] + list(item.get("rejection_reasons") or [])
                row["missing_reason"] = next((text for text in reasons if text), None)
            data_usage.append(row)

        return {
            "version": 3,
            "symbol": data.get("symbol"),
            "trace_id": trace_id(data),
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
            "data_usage": data_usage,
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
