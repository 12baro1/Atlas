"""Test that ConfluenceEngine incorporates the new advanced structure
features (trendline sweep, inverse FVG, EQH/EQL, internal structure)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from confluence_engine import ConfluenceEngine


def base_kwargs():
    return {
        "mtf": {"valid": False},
        "trend": {"trend": "BULLISH"},
        "entry": {"valid": False, "direction": "LONG"},
        "confirmation": {"confirmed": False},
        "premium_discount": {"valid": False},
        "liquidity_sweep": {"is_sweep": False, "is_breakout": False, "strength_score": 0},
        "ote": {"valid": False},
        "htf_orderblock": {"valid": False},
        "htf_fvg": {"valid": False},
        "breaker": [],
        "killzone": False,
        "session": False,
    }


def test_new_features_added_to_score():
    engine = ConfluenceEngine()
    kwargs = base_kwargs()
    base = engine.evaluate(**kwargs)

    boosted = dict(kwargs)
    boosted["trendline_sweep"] = {"active": True, "direction": "SELL_SIDE"}
    boosted["ifvg"] = [{"type": "BEARISH", "inverted": True, "index": 10}]
    boosted["eqh_eql"] = {"active": True, "eql": [{"price": 1}], "eqh": []}
    boosted["internal_structure"] = [
        {"index": 1, "label": "HH"}, {"index": 2, "label": "HL"}
    ]

    result = engine.evaluate(**boosted)

    assert result["score"] > base["score"]
    assert any("Trendline Sweep" in check for check in result["checks"])
    assert any("Inverse FVG" in check for check in result["checks"])
    assert any("Equal Low" in check for check in result["checks"])


def test_trendline_mismatch_direction_penalizes():
    engine = ConfluenceEngine()
    kwargs = base_kwargs()
    kwargs["trendline_sweep"] = {"active": True, "direction": "BUY_SIDE"}  # SHORT bekler, LONG entry
    result = engine.evaluate(**kwargs)
    assert any("◐" in check and "Trendline" in check for check in result["checks"])

def test_opposing_breaker_does_not_receive_directional_bonus():
    engine = ConfluenceEngine()
    kwargs = base_kwargs()
    baseline = engine.evaluate(**kwargs)
    kwargs["breaker"] = [{"breaker": True, "type": "BEARISH"}]
    result = engine.evaluate(**kwargs)
    assert result["score"] < baseline["score"]
    assert any("opposing direction" in check for check in result["checks"])


def test_opposing_inverse_fvg_is_not_counted_as_supportive():
    engine = ConfluenceEngine()
    kwargs = base_kwargs()
    kwargs["ifvg"] = [{"type": "BULLISH", "inverted": True, "index": 10}]
    result = engine.evaluate(**kwargs)
    assert any("opposing direction" in check for check in result["checks"])
