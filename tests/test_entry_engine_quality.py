import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from entry_engine import EntryEngine


def test_entry_engine_recommends_market_when_price_is_near_bullish_fvg():
    result = EntryEngine().generate(
        mtf={"entry": "LONG"},
        structure=[{"label": "HL", "kind": "LOW", "price": 99.5}],
        fvg=[{"type": "BULLISH", "from": 99.8, "to": 100.0, "filled": False}],
        orderblocks=[],
        current_price=100.05,
    )

    assert result["entry_type"] == "MARKET"
    assert result["entry"] == 100.05
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
