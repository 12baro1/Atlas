"""Backward-compatible imports for shared market-structure evidence services."""
from shared.market_structure_services import (
    trend_structure, displacement, volatility_regime, breakout_acceptance,
    statistical_deviation, rsi_divergence,
)

__all__ = [
    "trend_structure", "displacement", "volatility_regime",
    "breakout_acceptance", "statistical_deviation", "rsi_divergence",
]
