import math

import pytest

from core.analysis_utils import (
    clamp,
    direction_matches,
    extract_confidence,
    normalize_direction,
)


def test_clamp_handles_non_finite_and_non_numeric_values_safely():
    assert clamp(float("nan")) == 0
    assert clamp(float("inf")) == 0
    assert clamp("not-a-number") == 0
    assert clamp(120) == 100
    assert clamp(-5) == 0


def test_clamp_rejects_invalid_bounds():
    with pytest.raises(ValueError):
        clamp(5, lower=10, upper=1)
    with pytest.raises(ValueError):
        clamp(5, lower=float("-inf"), upper=10)


def test_direction_normalization_strips_whitespace():
    assert normalize_direction(" bullish ") == "LONG"
    assert direction_matches(" short ", "SHORT")


def test_extract_confidence_ignores_non_finite_values_and_uses_fallback():
    assert extract_confidence({"confidence": float("nan"), "score": 75}) == 75
    assert extract_confidence({"confidence": float("inf")}) == 0
    assert math.isfinite(extract_confidence({"best": {"score": 55}}))
