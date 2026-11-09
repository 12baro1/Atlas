"""
core/analysis_utils.py
Shared analysis helpers for directional and confidence-based engines.
"""

from __future__ import annotations

from typing import Any, Mapping
import math

LONG_VALUES = {"LONG", "BULLISH", "BUY"}
SHORT_VALUES = {"SHORT", "BEARISH", "SELL"}
NEUTRAL_VALUES = {"NONE", "WAIT", None, ""}

LONG_STATE_VALUES = {"DISCOUNT", "VALUE_LOW", "BELOW_POC", "ACCUMULATION"}
SHORT_STATE_VALUES = {"PREMIUM", "VALUE_HIGH", "ABOVE_POC", "DISTRIBUTION"}


def clamp(value: float, lower: float = 0, upper: float = 100) -> float:
    """Clamp finite numeric values; fail closed on invalid bounds or values."""
    lower = float(lower)
    upper = float(upper)
    if not math.isfinite(lower) or not math.isfinite(upper) or lower > upper:
        raise ValueError("clamp bounds must be finite and lower <= upper")
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return lower
    if not math.isfinite(numeric):
        return lower
    return max(lower, min(upper, numeric))


def normalize_direction(value: Any, default: str = "WAIT") -> str:
    if value is None:
        return default

    normalized = str(value).strip().upper()
    if normalized in LONG_VALUES:
        return "LONG"
    if normalized in SHORT_VALUES:
        return "SHORT"
    if normalized in NEUTRAL_VALUES:
        return default
    return normalized


def extract_direction(module: Mapping[str, Any] | None) -> str:
    if not isinstance(module, Mapping):
        return "NONE"

    for key in ("direction", "signal", "trend", "state_direction", "bias"):
        value = module.get(key)
        if value:
            normalized = normalize_direction(value, default="NONE")
            if normalized != "WAIT":
                return normalized

    best = module.get("best")
    if isinstance(best, Mapping):
        for key in ("direction", "signal", "trend", "state_direction", "bias"):
            value = best.get(key)
            if value:
                normalized = normalize_direction(value, default="NONE")
                if normalized != "WAIT":
                    return normalized

    state = module.get("state")
    if isinstance(state, str):
        upper_state = state.upper()
        if upper_state in LONG_STATE_VALUES:
            return "LONG"
        if upper_state in SHORT_STATE_VALUES:
            return "SHORT"

    return "NONE"


def extract_confidence(module: Mapping[str, Any] | None) -> float:
    if not isinstance(module, Mapping):
        return 0.0

    for key in ("confidence", "score", "phase_score", "strength_score"):
        value = module.get(key)
        if isinstance(value, (int, float)):
            return float(value)

    best = module.get("best")
    if isinstance(best, Mapping):
        for key in ("confidence", "score", "phase_score", "strength_score"):
            value = best.get(key)
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                return float(value)

    return 0.0


def is_active(module: Mapping[str, Any] | None) -> bool:
    return bool(isinstance(module, Mapping) and (module.get("active") or module.get("valid")))


def direction_matches(module_direction: Any, expected_direction: str) -> bool:
    normalized_expected = normalize_direction(expected_direction, default="WAIT")
    normalized_module = normalize_direction(module_direction, default="NONE")

    if normalized_expected not in {"LONG", "SHORT"}:
        return False

    if normalized_module in {"LONG", "SHORT"}:
        return normalized_module == normalized_expected

    if normalized_module in {"NONE", "WAIT"}:
        return False

    return normalized_module == normalized_expected


def state_matches_direction(module: Mapping[str, Any] | None, expected_direction: str) -> bool:
    if not isinstance(module, Mapping):
        return False

    state = module.get("state")
    if not isinstance(state, str):
        return False

    upper_state = state.upper()
    if normalize_direction(expected_direction, default="WAIT") == "LONG":
        return upper_state in LONG_STATE_VALUES
    if normalize_direction(expected_direction, default="WAIT") == "SHORT":
        return upper_state in SHORT_STATE_VALUES
    return False
