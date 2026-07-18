import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unicorn_engine import UnicornEngine


def _base_payload(direction, phase="Expansion"):
    setup_direction = direction
    sweep = {"buy_side": False, "sell_side": False}
    if direction == "BULLISH":
        sweep["sell_side"] = True
    else:
        sweep["buy_side"] = True

    return {
        "structure": [
            {
                "bos": True,
                "choch": True,
                "direction": setup_direction,
            }
        ],
        "breaker": [
            {
                "type": setup_direction,
                "low": 100.0,
                "high": 102.0,
                "strength": 80,
            }
        ],
        "fvg": [
            {
                "type": setup_direction,
                "from": 101.0,
                "to": 103.0,
                "strength": 85,
                "filled": False,
            }
        ],
        "market_phase": {"phase": phase},
        "liquidity_sweep": sweep,
        "smt": {"active": True, "direction": setup_direction, "confidence": 78},
        "orderblocks": [{"type": setup_direction}],
        "eqh_eql": {"active": True},
        "inducement": {"active": True},
        "ote": {"valid": True},
    }


def test_detects_bullish_unicorn_setup_with_levels():
    engine = UnicornEngine()

    result = engine.detect(
        {
            "15m": _base_payload("BULLISH"),
        }
    )

    assert result["active"] is True
    assert result["best"]["direction"] == "BULLISH"
    assert 0 <= result["best"]["confidence"] <= 100
    assert result["best"]["entry"] is not None
    assert result["best"]["tp1"] is not None


def test_detects_bearish_unicorn_setup_with_levels():
    engine = UnicornEngine()

    result = engine.detect(
        {
            "1h": _base_payload("BEARISH"),
        }
    )

    assert result["active"] is True
    assert result["best"]["direction"] == "BEARISH"
    assert 0 <= result["best"]["confidence"] <= 100
    assert result["best"]["stop_loss"] is not None


def test_returns_inactive_when_no_breaker_fvg_overlap():
    engine = UnicornEngine()

    payload = _base_payload("BULLISH")
    payload["fvg"] = [
        {
            "type": "BULLISH",
            "from": 104.0,
            "to": 105.0,
            "strength": 80,
            "filled": False,
        }
    ]

    result = engine.detect({"4h": payload})

    assert result["active"] is False
    assert result["best"] is None
    assert result["confidence"] == 0
