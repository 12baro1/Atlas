"""Regression tests for independent strategy evidence and malformed OHLC isolation."""
from unittest.mock import patch

from strategy_lab import _finalize_candidate_geometry


def test_invalid_structure_timeframe_does_not_mask_valid_timeframe():
    # No pivots are present, but a valid independent timeframe should be
    # evaluated rather than rejected as INVALID_OHLC_IN_STRUCTURE_DATA.
    valid = []
    for i in range(15):
        value = 100.0 + (i % 5)
        valid.append({"open": value, "high": value + 1, "low": value - 1,
                      "close": value, "volume": 100})
    invalid = [{"open": 100, "high": 99, "low": 101, "close": 100, "volume": 10}]
    candidate = {"direction": "LONG", "entry": 105.0,
                 "stop_loss": 103.0, "atr": 1.0}
    result = _finalize_candidate_geometry(candidate, [invalid, valid])
    assert result != "INVALID_OHLC_IN_STRUCTURE_DATA"


def test_all_invalid_structure_timeframes_rejected():
    invalid = [{"open": 100, "high": 99, "low": 101, "close": 100, "volume": 10}]
    candidate = {"direction": "LONG", "entry": 105.0,
                 "stop_loss": 103.0, "atr": 1.0}
    assert _finalize_candidate_geometry(candidate, [invalid]) == "INVALID_OHLC_IN_STRUCTURE_DATA"
