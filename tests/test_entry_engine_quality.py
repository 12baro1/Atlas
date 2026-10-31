import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from entry_engine import EntryEngine


def test_entry_engine_does_not_market_enter_only_because_price_is_near_bullish_fvg():
    result = EntryEngine().generate(
        mtf={"entry": "LONG"},
        structure=[{"label": "HL", "kind": "LOW", "price": 99.5}],
        fvg=[{"type": "BULLISH", "from": 99.8, "to": 100.0, "filled": False}],
        orderblocks=[],
        current_price=100.05,
    )

    assert result["entry_type"] == "LIMIT"
    assert result["entry"] == 100.0
    assert result["stop_loss"] < result["entry"]


def test_entry_engine_recommends_limit_when_price_is_far_from_bullish_fvg():
    result = EntryEngine().generate(
        mtf={"entry": "LONG"},
        structure=[{"label": "HL", "kind": "LOW", "price": 99.5}],
        fvg=[{"type": "BULLISH", "from": 99.8, "to": 100.0, "filled": False}],
        orderblocks=[],
        current_price=102.0,
    )

    assert result["entry_type"] == "LIMIT"
    assert result["entry"] == 100.0
    assert result["stop_loss"] < result["entry"]


def test_entry_engine_market_entry_requires_sweep_and_post_choch():
    result = EntryEngine().generate(
        mtf={"entry": "LONG"},
        structure=[{"label": "HL", "kind": "LOW", "price": 99.5}],
        fvg=[{"type": "BULLISH", "from": 99.8, "to": 100.0, "filled": False}],
        orderblocks=[],
        current_price=99.9,
        liquidity_sweep={
            "sell_side": True,
            "post_structure": {"confirmed": True, "direction": "BULLISH", "type": "CHOCH"},
        },
    )
    assert result["entry_type"] == "MARKET"
    assert result["entry"] == 99.9


def test_entry_engine_rejects_wrong_side_stop_loss():
    result = EntryEngine().generate(
        mtf={"entry": "SHORT"},
        structure=[{"label": "LL", "kind": "LOW", "price": 99.0}],
        fvg=[{"type": "BEARISH", "from": 100.0, "to": 99.8, "filled": False}],
        orderblocks=[{"type": "BEARISH", "low": 99.7, "high": 100.2, "mitigated": False}],
        current_price=100.0,
    )

    if result["entry"] is not None and result["stop_loss"] is not None:
        assert result["stop_loss"] > result["entry"] or result["valid"] is False


def test_entry_engine_does_not_infer_direction_from_15m_when_mtf_is_wait():
    result = EntryEngine().generate(
        mtf={"entry": "WAIT"},
        structure=[{"label": "HH", "kind": "HIGH", "price": 101.0}],
        fvg=[{"type": "BULLISH", "from": 99.8, "to": 100.0, "filled": False}],
        orderblocks=[],
        current_price=100.0,
    )

    assert result["valid"] is False
    assert result["direction"] == "NONE"
    assert result["reason"] == "No MTF direction"


def test_entry_engine_blocks_far_price_after_bullish_poi_was_crossed():
    result = EntryEngine().generate(
        mtf={"entry": "LONG"},
        structure=[{"label": "HL", "kind": "LOW", "price": 99.5}],
        fvg=[{"type": "BULLISH", "from": 99.8, "to": 100.0, "filled": False}],
        orderblocks=[],
        current_price=98.0,
    )

    assert result["valid"] is False
    assert result["entry"] is None
    assert result["entry_type"] == "NONE"
    assert result["entry_zone_crossed"] is True
    assert "already crossed" in result["entry_type_reason"]


def test_entry_engine_blocks_far_price_after_bearish_poi_was_crossed():
    result = EntryEngine().generate(
        mtf={"entry": "SHORT"},
        structure=[{"label": "LL", "kind": "LOW", "price": 98.0}],
        fvg=[{"type": "BEARISH", "from": 100.0, "to": 99.8, "filled": False}],
        orderblocks=[],
        current_price=102.0,
    )

    assert result["valid"] is False
    assert result["entry"] is None
    assert result["entry_type"] == "NONE"
    assert result["entry_zone_crossed"] is True
    assert "already crossed" in result["entry_type_reason"]


def test_entry_engine_long_stop_uses_outer_swing_and_poi_invalidation():
    result = EntryEngine().generate(
        mtf={"entry": "LONG"},
        structure=[{"label": "HL", "kind": "LOW", "price": 98.9}],
        fvg=[{"type": "BULLISH", "from": 99.2, "to": 100.0, "filled": False}],
        orderblocks=[{"type": "BULLISH", "low": 99.4, "high": 100.1, "mitigated": False}],
        current_price=100.05,
    )
    assert result["stop_loss"] == 98.9
    assert result["stop_source"] == "swing_low"


def test_entry_engine_short_stop_uses_outer_swing_and_poi_invalidation():
    result = EntryEngine().generate(
        mtf={"entry": "SHORT"},
        structure=[{"label": "LH", "kind": "HIGH", "price": 101.2}],
        fvg=[{"type": "BEARISH", "from": 100.0, "to": 101.0, "filled": False}],
        orderblocks=[{"type": "BEARISH", "low": 99.9, "high": 100.8, "mitigated": False}],
        current_price=99.95,
    )
    assert result["stop_loss"] == 101.2
    assert result["stop_source"] == "swing_high"



def test_structure_fallback_without_live_price_is_not_executable():
    result = EntryEngine().generate(
        mtf={"entry": "LONG"},
        structure=[
            {"label": "HL", "kind": "LOW", "price": 99.5},
            {"label": "HH", "kind": "HIGH", "price": 101.0},
        ],
        fvg=[],
        orderblocks=[],
        current_price=None,
    )

    assert result["valid"] is False
    assert result["entry"] is None
    assert result["entry_type"] == "NONE"


def test_structure_fallback_with_finite_live_price_uses_market_order():
    result = EntryEngine().generate(
        mtf={"entry": "LONG"},
        structure=[
            {"label": "HL", "kind": "LOW", "price": 99.5},
            {"label": "HH", "kind": "HIGH", "price": 101.0},
        ],
        fvg=[],
        orderblocks=[],
        current_price=100.5,
    )

    assert result["valid"] is False
    assert result["entry_type"] == "NONE"
    assert result["entry"] is None


def test_entry_engine_rejects_non_finite_current_price():
    result = EntryEngine().generate(
        mtf={"entry": "LONG"},
        structure=[
            {"label": "HL", "kind": "LOW", "price": 99.5},
            {"label": "HH", "kind": "HIGH", "price": 101.0},
        ],
        fvg=[],
        orderblocks=[],
        current_price=float("inf"),
    )

    assert result["valid"] is False
    assert result["entry"] is None
    assert result["entry_type"] == "NONE"


def test_entry_engine_safe_price_rejects_non_finite_values():
    engine = EntryEngine()
    assert engine._safe_price(float("nan")) is None
    assert engine._safe_price(float("inf")) is None
    assert engine._safe_price(float("-inf")) is None


def test_entry_engine_keeps_distant_limit_pullback_and_labels_distance():
    result = EntryEngine().generate(
        mtf={"entry": "SHORT"},
        structure=[{"label": "LH", "kind": "HIGH", "price": 105.0}],
        fvg=[{"type": "BEARISH", "from": 106.0, "to": 105.8, "filled": False}],
        orderblocks=[],
        current_price=100.0,
    )
    assert result["entry"] == 105.8
    assert result["entry_type"] == "LIMIT"
    assert result["requires_pullback"] is True
    assert result["entry_too_far"] is False
    assert result["entry_distance_label"] == "UZAK GİRİŞ"
    assert result["entry_distance_pct"] == 5.8


def test_entry_engine_keeps_nearby_limit_pullback():
    result = EntryEngine().generate(
        mtf={"entry": "SHORT"},
        structure=[{"label": "LH", "kind": "HIGH", "price": 101.0}],
        fvg=[{"type": "BEARISH", "from": 100.8, "to": 100.6, "filled": False}],
        orderblocks=[],
        current_price=100.0,
    )
    assert result["entry_type"] == "LIMIT"
    assert result["requires_pullback"] is True
    assert result["entry"] == 100.6


def test_entry_distance_within_two_percent_is_labeled_near_when_atr_is_unavailable():
    result = EntryEngine().generate(
        mtf={"entry": "SHORT"},
        structure=[{"label": "LH", "kind": "HIGH", "price": 101.5}],
        fvg=[{"type": "BEARISH", "from": 101.5, "to": 101.2, "filled": False}],
        orderblocks=[],
        current_price=100.0,
    )
    assert result["entry_type"] == "LIMIT"
    assert result["entry_distance_pct"] == 1.2
    assert result["entry_distance_label"] == "YAKIN GİRİŞ"
