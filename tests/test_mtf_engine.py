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


def test_neutral_higher_timeframes_allow_only_sweep_and_choch_confirmed_reversal():
    structure = [{"label": "HH", "choch": True, "direction": "BULLISH"}]
    sweep = {
        "is_sweep": True,
        "sell_side": True,
        "buy_side": False,
        "sweep_side": "SELL_SIDE",
        "post_structure": {"confirmed": True, "direction": "BULLISH"},
    }
    result = MTFEngine().detect([], [], [], structure, liquidity_sweep=sweep)
    assert result["entry"] == "LONG"
    assert result["entry_source"] == "CONFIRMED_15M_REVERSAL"
    assert result["valid"] is True


def test_ltf_reversal_without_sweep_confirmation_does_not_create_direction():
    structure = [{"label": "HH", "choch": True, "direction": "BULLISH"}]
    result = MTFEngine().detect([], [], [], structure)
    assert result["entry"] == "NONE"
    assert result["valid"] is False


def test_ltf_reversal_does_not_override_opposing_higher_timeframe():
    structure = [{"label": "HH", "choch": True, "direction": "BULLISH"}]
    sweep = {
        "is_sweep": True,
        "sell_side": True,
        "buy_side": False,
        "sweep_side": "SELL_SIDE",
        "post_structure": {"confirmed": True, "direction": "BULLISH"},
    }
    result = MTFEngine().detect([], _bearish(), [], structure, liquidity_sweep=sweep)
    assert result["entry"] == "NONE"
    assert result["valid"] is False
}
