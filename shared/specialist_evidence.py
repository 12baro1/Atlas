"""Routing contract for shared specialist analysis evidence.

Specialist outputs are shared as read-only analysis context. Strategy generators
remain independent: this module never converts evidence into a strategy decision.
"""
from __future__ import annotations

# Only upstream analysis motors are shared with the six non-SMC strategies.
# SMC-owned submotors remain inside strategies.smc and are not exported here.
STRATEGY_SPECIALIST_MOTORS = {
    "trend_pullback": (
        "trend", "market_regime", "mtf", "bos", "choch", "liquidity",
        "orderblocks", "fvg", "liquidity_sweep",
    ),
    "volatility_breakout": (
        "market_regime", "orderbook", "volume_profile", "liquidity",
        "bos", "choch",
    ),
    "mean_reversion": (
        "market_phase", "market_regime", "volume_profile", "orderbook",
        "liquidity", "liquidity_sweep",
    ),
    "liquidation_cascade": (
        "market_regime", "orderbook", "institutional", "volume_profile",
        "liquidity",
    ),
    "orderflow_momentum": (
        "orderbook", "liquidity", "liquidity_sweep", "institutional",
        "volume_profile",
    ),
    "relative_strength": (
        "correlation", "mtf", "market_regime", "institutional",
    ),
}

# These are analysis-only motor outputs. Execution, risk, signal, learning,
# filters and decision components must never be routed back into strategies.
SHARED_ANALYSIS_MOTORS = frozenset(
    motor for motors in STRATEGY_SPECIALIST_MOTORS.values() for motor in motors
)


def build_strategy_evidence(records):
    """Keep completed, allow-listed motor outputs in their execution order."""
    output = []
    for record in records or ():
        if not isinstance(record, dict):
            continue
        motor = str(record.get("motor") or "")
        if motor not in SHARED_ANALYSIS_MOTORS or record.get("status") != "COMPLETED":
            continue
        output.append({
            "sequence": record.get("sequence"),
            "motor": motor,
            "method": str(record.get("method") or ""),
            "status": "COMPLETED",
            "output": record.get("output"),
            "event_ids": list(record.get("event_ids") or []),
        })
    return output


def evidence_for_strategy(data, strategy_id):
    """Return only the specialist outputs assigned to this strategy."""
    allowed = set(STRATEGY_SPECIALIST_MOTORS.get(strategy_id, ()))
    records = data.get("specialist_evidence") or ()
    return [
        record for record in records
        if isinstance(record, dict)
        and record.get("status") == "COMPLETED"
        and record.get("motor") in allowed
    ]


def attach_strategy_evidence(candidate, records):
    """Attach traceable provenance, not raw motor objects, to a generated setup."""
    if not isinstance(candidate, dict):
        return candidate
    rows = []
    for record in records or ():
        if not isinstance(record, dict):
            continue
        rows.append({
            "motor": record.get("motor"),
            "method": record.get("method"),
            "event_ids": list(record.get("event_ids") or []),
        })
    candidate["specialist_evidence"] = rows
    candidate["specialist_evidence_sources"] = sorted({
        str(row["motor"]) for row in rows if row.get("motor")
    })
    candidate["specialist_evidence_count"] = len(rows)
    candidate["specialist_evidence_event_ids"] = sorted({
        str(event_id)
        for row in rows
        for event_id in row.get("event_ids") or []
        if event_id
    })
    return candidate
