from price_precision import snap_price_to_tick
from strategy_lab import _snap_candidate_to_exchange_tick


def test_decimal_tick_snapping_preserves_sub_eight_decimal_ticks():
    assert snap_price_to_tick(0.00000000037, 0.0000000001, "nearest") == 0.0000000004
    assert snap_price_to_tick(0.0673593664, 0.000001, "floor") == 0.067359
    assert snap_price_to_tick(0.0673593664, 0.000001, "ceiling") == 0.06736


def test_common_strategy_filter_snaps_long_geometry_outward():
    candidate = {
        "direction": "LONG",
        "entry_type": "LIMIT",
        "entry": 100.004,
        "stop_loss": 95.004,
        "tp1": 105.004,
        "tp2": 110.004,
        "tp3": 115.004,
    }
    _snap_candidate_to_exchange_tick(candidate, 0.01)
    assert candidate["entry"] == 100.0
    assert candidate["stop_loss"] == 95.0
    assert candidate["tp1"] == 105.01
    assert candidate["tp2"] == 110.01
    assert candidate["tp3"] == 115.01


def test_common_strategy_filter_snaps_short_geometry_outward():
    candidate = {
        "direction": "SHORT",
        "entry_type": "LIMIT",
        "entry": 100.004,
        "stop_loss": 105.004,
        "tp1": 95.004,
        "tp2": 90.004,
        "tp3": 85.004,
    }
    _snap_candidate_to_exchange_tick(candidate, 0.01)
    assert candidate["entry"] == 100.01
    assert candidate["stop_loss"] == 105.01
    assert candidate["tp1"] == 95.0
    assert candidate["tp2"] == 90.0
    assert candidate["tp3"] == 85.0
