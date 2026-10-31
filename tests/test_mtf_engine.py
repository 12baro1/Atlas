import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtf_engine import MTFEngine


def _bullish():
    return [
        {"kind": "HIGH", "label": "HH"},
        {"kind": "LOW", "label": "HL"},
    ]


def _bearish():
    return [
        {"kind": "HIGH", "label": "LH"},
        {"kind": "LOW", "label": "LL"},
    ]


def test_mtf_does_not_treat_missing_structure_as_bearish():
    result = MTFEngine().detect([], [], [], [])
    assert result["weekly"] == result["daily"] == result["h4"] == "NEUTRAL"
    assert result["entry"] == "NONE"
    assert result["valid"] is False


def test_mtf_requires_two_complete_bearish_structures_for_short():
    result = MTFEngine().detect([], _bearish(), _bearish(), [])
    assert result["weekly"] == "NEUTRAL"
    assert result["daily"] == result["h4"] == "BEARISH"
    assert result["entry"] == "SHORT"
    assert result["valid"] is True


def test_mtf_requires_two_complete_bullish_structures_for_long():
    result = MTFEngine().detect(_bullish(), _bullish(), [], [])
    assert result["weekly"] == result["daily"] == "BULLISH"
    assert result["h4"] == "NEUTRAL"
    assert result["entry"] == "LONG"
    assert result["valid"] is True


def test_mtf_single_higher_high_is_not_a_bullish_trend():
    result = MTFEngine().detect([{"kind": "HIGH", "label": "HH"}], [], [], [])
    assert result["weekly"] == "NEUTRAL"
    assert result["entry"] == "NONE"


def test_mtf_conflicting_timeframes_do_not_force_a_direction():
    result = MTFEngine().detect(_bullish(), _bearish(), _bullish(), [])
    assert result["entry"] == "NONE"
    assert result["valid"] is False
