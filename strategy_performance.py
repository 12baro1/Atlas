"""Conservative, strategy-specific edge validation for the seven-strategy selector.

A candidate strength score is not a probability of winning. Experimental engines
are eligible for selection only after independent, cost-adjusted, out-of-sample
results meet minimum sample and confidence gates.
"""
from __future__ import annotations

import math


DEFAULT_GATES = {
    "min_is_trades": 30,
    "min_oos_trades": 15,
    "min_profit_factor": 1.15,
    "min_oos_profit_factor": 1.05,
    "min_oos_expectancy_r": 0.0,
    "min_confidence_lower_bound_r": 0.0,
}


def evaluate_strategy_edge(stats, gates=None):
    """Return a transparent eligibility decision; missing evidence fails closed.

    Required fields: is_trades, is_expectancy_r, is_profit_factor,
    is_expectancy_std_r, oos_trades, oos_expectancy_r, oos_profit_factor.
    Expectancy and PF must already be net of modeled execution costs.
    """
    rules = dict(DEFAULT_GATES)
    if gates:
        rules.update(gates)
    if not isinstance(stats, dict):
        return {"eligible": False, "status": "NO_PERFORMANCE_RECORD", "reasons": ["strategy-specific performance record missing"]}

    required = (
        "is_trades", "is_expectancy_r", "is_profit_factor",
        "is_expectancy_std_r", "oos_trades", "oos_expectancy_r",
        "oos_profit_factor",
    )
    missing = [key for key in required if stats.get(key) is None]
    if missing:
        return {"eligible": False, "status": "INCOMPLETE_PERFORMANCE_RECORD", "reasons": [f"missing {key}" for key in missing]}

    try:
        values = {key: float(stats[key]) for key in required}
    except (TypeError, ValueError, OverflowError):
        return {"eligible": False, "status": "INVALID_PERFORMANCE_RECORD", "reasons": ["non-numeric performance field"]}
    if not all(math.isfinite(value) for value in values.values()):
        return {"eligible": False, "status": "INVALID_PERFORMANCE_RECORD", "reasons": ["non-finite performance field"]}

    reasons = []
    if values["is_trades"] < rules["min_is_trades"]:
        reasons.append("insufficient in-sample trade count")
    if values["oos_trades"] < rules["min_oos_trades"]:
        reasons.append("insufficient out-of-sample trade count")
    if values["is_profit_factor"] < rules["min_profit_factor"]:
        reasons.append("in-sample profit factor below gate")
    if values["oos_profit_factor"] < rules["min_oos_profit_factor"]:
        reasons.append("out-of-sample profit factor below gate")
    if values["oos_expectancy_r"] <= rules["min_oos_expectancy_r"]:
        reasons.append("out-of-sample net expectancy is not positive")

    # Approximate 95% lower confidence bound for mean R. This is a conservative
    # promotion gate, not a claim that trading returns are normally distributed.
    n = max(1.0, values["is_trades"])
    standard_error = values["is_expectancy_std_r"] / math.sqrt(n)
    lower_bound = values["is_expectancy_r"] - 1.96 * standard_error
    if lower_bound <= rules["min_confidence_lower_bound_r"]:
        reasons.append("in-sample expectancy confidence lower bound does not clear zero")

    eligible = not reasons
    return {
        "eligible": eligible,
        "status": "VALIDATED_EDGE" if eligible else "EDGE_NOT_VALIDATED",
        "reasons": reasons,
        "expectancy_lower_bound_r": round(lower_bound, 4),
        "selection_quality": round(max(0.0, values["oos_expectancy_r"]) * min(values["oos_profit_factor"], 3.0), 4) if eligible else 0.0,
    }


def rank_validated_candidate(candidate, stats, regime_fit=1.0):
    """Rank only with independently validated OOS statistics, never setup strength."""
    edge = evaluate_strategy_edge(stats)
    if not edge["eligible"]:
        return None
    try:
        fit = float(regime_fit)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(fit) or fit <= 0:
        return None
    return {
        "strategy_id": candidate.get("strategy_id"),
        "score": round(edge["selection_quality"] * fit, 6),
        "edge": edge,
    }
