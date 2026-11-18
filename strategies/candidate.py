"""Shared raw setup contract used before common eligibility checks."""
import math

from config import Config


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
