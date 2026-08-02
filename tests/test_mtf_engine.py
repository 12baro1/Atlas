import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtf_engine import MTFEngine


def test_mtf_does_not_treat_missing_structure_as_bearish():
    result = MTFEngine().detect([], [], [], [])

    assert result["weekly"] == "NEUTRAL"
    assert result["daily"] == "NEUTRAL"
    assert result["h4"] == "NEUTRAL"
    assert result["entry"] == "NONE"
    assert result["valid"] is False


def test_mtf_requires_two_real_bearish_timeframes_for_short():
    result = MTFEngine().detect(
        [],
        [{"label": "LL"}],
        [{"label": "LH"}],
        [],
    )

    assert result["weekly"] == "NEUTRAL"
    assert result["daily"] == "BEARISH"
    assert result["h4"] == "BEARISH"
    assert result["entry"] == "SHORT"
    assert result["valid"] is True


def test_mtf_requires_two_real_bullish_timeframes_for_long():
    result = MTFEngine().detect(
        [{"label": "HH"}],
        [{"label": "HL"}],
        [],
        [],
    )

    assert result["weekly"] == "BULLISH"
    assert result["daily"] == "BULLISH"
    assert result["h4"] == "NEUTRAL"
    assert result["entry"] == "LONG"
    assert result["valid"] is True
