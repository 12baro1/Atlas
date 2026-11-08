import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtf_engine import MTFEngine
from trend_engine import TrendEngine


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


def _confirmed_sweep(side="SELL_SIDE"):
    direction = "BULLISH" if side == "SELL_SIDE" else "BEARISH"
    label = "HH" if direction == "BULLISH" else "LL"
    return (
        [{"label": label, "choch": True, "direction": direction}],
        {
            "is_sweep": True,
            "sell_side": side == "SELL_SIDE",
            "buy_side": side == "BUY_SIDE",
            "sweep_side": side,
            "post_structure": {"confirmed": True, "direction": direction},
        },
    )


def test_mtf_does_not_treat_missing_structure_as_bearish():
    result = MTFEngine().detect([], [], [], [])
    assert result["weekly"] == result["daily"] == result["h4"] == "NEUTRAL"
    assert result["entry"] == "NONE"
    assert result["valid"] is False


def test_h4_bearish_is_enough_when_weekly_is_neutral():
    result = MTFEngine().detect([], [], _bearish(), [])
    assert result["entry"] == "SHORT"
    assert result["entry_source"] == "H4_STRUCTURE"
    assert result["valid"] is True


def test_h4_bullish_is_enough_when_daily_is_bearish_but_weekly_is_neutral():
    result = MTFEngine().detect([], _bearish(), _bullish(), [])
    assert result["entry"] == "LONG"
    assert result["daily_h4_conflict"] is True
    assert result["weekly_h4_conflict"] is False


def test_weekly_opposing_h4_is_context_not_directional_veto():
    result = MTFEngine().detect(_bearish(), [], _bullish(), [])
    assert result["entry"] == "LONG"
    assert result["entry_source"] == "H4_STRUCTURE"
    assert result["weekly_h4_conflict"] is True
    assert result["valid"] is True
    assert result["direction_reason"] == "h4_bullish_weekly_countertrend"


def test_weekly_and_h4_alignment_is_reported():
    result = MTFEngine().detect(_bearish(), [], _bearish(), [])
    assert result["entry"] == "SHORT"
    assert result["entry_source"] == "H4_STRUCTURE"


def test_mtf_single_higher_high_is_not_a_bullish_trend():
    result = MTFEngine().detect([{"kind": "HIGH", "label": "HH"}], [], [], [])
    assert result["weekly"] == "NEUTRAL"
    assert result["entry"] == "NONE"


def test_neutral_h4_allows_only_sweep_and_choch_confirmed_reversal():
    structure, sweep = _confirmed_sweep("SELL_SIDE")
    result = MTFEngine().detect([], [], [], structure, liquidity_sweep=sweep)
    assert result["entry"] == "LONG"
    assert result["entry_source"] == "CONFIRMED_15M_REVERSAL"
    assert result["valid"] is True


def test_ltf_reversal_without_sweep_confirmation_does_not_create_direction():
    structure, _ = _confirmed_sweep("SELL_SIDE")
    result = MTFEngine().detect([], [], [], structure)
    assert result["entry"] == "NONE"
    assert result["valid"] is False


def test_ltf_reversal_does_not_override_opposing_weekly_context():
    structure, sweep = _confirmed_sweep("SELL_SIDE")
    result = MTFEngine().detect(_bearish(), [], [], structure, liquidity_sweep=sweep)
    assert result["entry"] == "NONE"
    assert result["valid"] is False


def test_ltf_reversal_does_not_override_directional_h4_structure():
    structure, sweep = _confirmed_sweep("SELL_SIDE")
    result = MTFEngine().detect([], _bearish(), _bearish(), structure, liquidity_sweep=sweep)
    assert result["entry"] == "SHORT"
    assert result["entry_source"] == "H4_STRUCTURE"


def test_trend_engine_uses_primary_h4_direction_not_flat_three_timeframe_vote():
    result = TrendEngine().calculate({
        "entry": "LONG",
        "weekly": "NEUTRAL",
        "daily": "BEARISH",
        "h4": "BULLISH",
    })
    assert result["trend"] == "BULLISH"
    assert result["strength"] == 2



def test_h4_recent_confirmed_bos_can_set_direction_before_full_swing_pair():
    h4 = [
        {"kind": "LOW", "label": "LL"},
        {"kind": "HIGH", "label": "LH"},
        {"kind": "LOW", "label": "LL"},
        {"kind": "HIGH", "label": "HH", "bos": True, "direction": "BULLISH"},
    ]
    result = MTFEngine().detect([], [], h4, [])
    assert result["h4"] == "BULLISH"
    assert result["entry"] == "LONG"
    assert result["entry_source"] == "H4_STRUCTURE"


def test_h4_lone_swing_label_without_confirmed_bos_stays_neutral():
    h4 = [{"kind": "HIGH", "label": "HH"}]
    result = MTFEngine().detect([], [], h4, [])
    assert result["h4"] == "NEUTRAL"
    assert result["entry"] == "NONE"


def test_recent_h4_opposing_break_supersedes_older_bos():
    h4 = [
        {"kind": "HIGH", "label": "HH", "bos": True, "direction": "BULLISH"},
        {"kind": "LOW", "label": "LL", "bos": True, "direction": "BEARISH"},
    ]
    result = MTFEngine().detect([], [], h4, [])
    assert result["h4"] == "BEARISH"
    assert result["entry"] == "SHORT"


def test_h4_bos_remains_active_after_ordinary_swings_are_appended():
    h4 = [
        {"kind": "HIGH", "label": "HH", "bos": True, "direction": "BULLISH"},
        {"kind": "HIGH", "label": "H?"},
        {"kind": "LOW", "label": "L?"},
        {"kind": "HIGH", "label": "H?"},
        {"kind": "LOW", "label": "L?"},
        {"kind": "HIGH", "label": "H?"},
    ]
    result = MTFEngine().detect([], [], h4, [])
    assert result["h4"] == "BULLISH"
    assert result["entry"] == "LONG"


def test_latest_h4_opposing_break_overrides_an_older_complete_swing_pair():
    h4 = [
        {"kind": "HIGH", "label": "HH"},
        {"kind": "LOW", "label": "HL"},
        {"kind": "EVENT", "label": "LL", "bos": True, "direction": "BEARISH"},
    ]
    result = MTFEngine().detect([], [], h4, [])
    assert result["h4"] == "BEARISH"
    assert result["entry"] == "SHORT"
