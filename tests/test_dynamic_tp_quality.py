import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dynamic_tp_engine import DynamicTPEngine


def test_strict_mode_does_not_fabricate_rr_targets():
    result = DynamicTPEngine().calculate(
        direction="LONG",
        entry=100.0,
        stop_loss=99.0,
        liquidity=[],
        fvg=[],
        orderblocks=[],
        structure=[],
        allow_rr_fallback=False,
    )

    assert result["tp1"] is None
    assert result["tp2"] is None
    assert result["tp3"] is None
    assert result["reason"] == "no_valid_structural_targets"
    assert result["synthetic_targets"] is False


def test_legacy_fallback_is_explicitly_marked_synthetic():
    result = DynamicTPEngine().calculate(
        direction="SHORT",
        entry=100.0,
        stop_loss=101.0,
        liquidity=[],
        fvg=[],
        orderblocks=[],
        structure=[],
        allow_rr_fallback=True,
    )

    assert result["tp1"] == 99.0
    assert result["tp2"] == 98.0
    assert result["tp3"] == 97.0
    assert result["synthetic_targets"] is True
    assert "rr_fallback" in result["sources"]


def test_long_targets_use_only_buy_side_liquidity_and_fresh_opposing_pois():
    engine = DynamicTPEngine()
    targets = engine._collect_targets(
        direction="LONG",
        entry=100.0,
        liquidity=[
            {"type": "BUY_SIDE", "price": 104.0},
            {"type": "SELL_SIDE", "price": 96.0},
        ],
        fvg=[
            {"type": "BEARISH", "from": 103.0, "to": 104.0, "filled": False},
            {"type": "BEARISH", "from": 107.0, "to": 108.0, "filled": True},
            {"type": "BULLISH", "from": 101.0, "to": 102.0, "filled": False},
        ],
        orderblocks=[
            {"type": "BEARISH", "low": 105.0, "high": 106.0, "mitigated": False},
            {"type": "BEARISH", "low": 109.0, "high": 110.0, "mitigated": True},
            {"type": "BULLISH", "low": 97.0, "high": 98.0, "mitigated": False},
        ],
        structure=[],
    )
    assert targets == [103.0, 104.0, 105.0]


def test_short_targets_use_only_sell_side_liquidity_and_fresh_opposing_pois():
    engine = DynamicTPEngine()
    targets = engine._collect_targets(
        direction="SHORT",
        entry=100.0,
        liquidity=[
            {"type": "SELL_SIDE", "price": 96.0},
            {"type": "BUY_SIDE", "price": 104.0},
        ],
        fvg=[
            {"type": "BULLISH", "from": 96.0, "to": 97.0, "filled": False},
            {"type": "BULLISH", "from": 92.0, "to": 93.0, "filled": True},
            {"type": "BEARISH", "from": 98.0, "to": 99.0, "filled": False},
        ],
        orderblocks=[
            {"type": "BULLISH", "low": 94.0, "high": 95.0, "mitigated": False},
            {"type": "BULLISH", "low": 90.0, "high": 91.0, "mitigated": True},
            {"type": "BEARISH", "low": 102.0, "high": 103.0, "mitigated": False},
        ],
        structure=[],
    )
    assert targets == [97.0, 96.0, 95.0]
