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
    assert result["synthetic_targets"] is True


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
