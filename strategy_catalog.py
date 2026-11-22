"""Canonical live Atlas roles.

Only TRADE_STRATEGY_LABELS may create candidates, reach the shared filter,
enter the outcome journal, or be counted as trade strategies.
SPECIALIST_LABELS are read-only market evidence; they never open trades.
"""
from __future__ import annotations

TRADE_STRATEGY_LABELS = {
    "trend_pullback": "Trend Pullback",
    "volatility_breakout": "Volatility Breakout",
    "mean_reversion": "Mean Reversion",
    "orderflow_momentum": "Orderflow Momentum",
    "smc": "SMC",
}

SPECIALIST_LABELS = {
    "relative_strength": "Relative Strength",
    "liquidation_cascade": "Liquidation Cascade",
}

TRADE_STRATEGY_IDS = frozenset(TRADE_STRATEGY_LABELS)
SPECIALIST_IDS = frozenset(SPECIALIST_LABELS)

assert TRADE_STRATEGY_IDS.isdisjoint(SPECIALIST_IDS)
