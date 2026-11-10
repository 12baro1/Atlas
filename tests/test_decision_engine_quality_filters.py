import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decision_engine import DecisionEngine


def _supportive_context(**overrides):
    context = {
        "signal": {"signal": "LONG", "confidence": 96, "grade": "S+", "strength": "ELITE"},
        "confluence": {"score": 82, "checks": ["✔ Stack Confluence (Sweep+OB+FVG+SMT+Phase)"]},
        "entry": {"valid": True},
        "risk": {"entry": 100.0, "stop_loss": 99.0, "rr": 3.5, "risk": 1.0, "position_size": 1.0,
                 "weighted_net_rr": 3.0},
        "mtf": {"valid": True, "entry": "LONG"},
        "ote": {"valid": True},
        "htf_orderblock": {"valid": True},
        "liquidity_sweep": {"is_sweep": True, "strength_score": 80},
        "market_phase": {"phase": "Expansion"},
        "cisd": {"active": True, "direction": "BULLISH", "confidence": 80},
        "volume_profile": {"active": True, "direction": "BULLISH", "confidence": 80},
        "institutional": {"active": False, "direction": "NONE", "confidence": 0},
        "unicorn": {"active": True, "direction": "BULLISH", "best": {"direction": "BULLISH"}, "confidence": 80},
        "smt": {"active": True, "direction": "LONG", "confidence": 80},
        "trade_quality": {"allowed": True, "blockers": []},
    }
    context.update(overrides)
    return context


def test_decision_executes_when_quality_filters_pass():
    engine = DecisionEngine()
    result = engine.decide(**_supportive_context(trade_quality={"allowed": True, "blockers": []}))
    assert result["action"] == "EXECUTE"
    assert result["trade_quality"]["allowed"] is True


def test_decision_skips_when_quality_filter_critical_blocker():
    engine = DecisionEngine()
    result = engine.decide(
        **_supportive_context(
            trade_quality={
                "allowed": False,
                "blockers": [
                    "HTF/LTF conflict: 4H BEARISH opposes LONG without confirmed reversal"
                ],
            }
        )
    )
    assert result["action"] == "SKIP"
    assert "HTF/LTF conflict" in " ".join(result["critical_blockers"])


def test_decision_skips_when_multiple_filters_block():
    engine = DecisionEngine()
    result = engine.decide(
        **_supportive_context(
            trade_quality={
                "allowed": False,
                "blockers": [
                    "Entry too far: 3.00 ATR from market price (MARKET)",
                    "TP/RR: net RR 1.00 below minimum 1.5 after costs",
                ],
            }
        )
    )
    assert result["action"] == "SKIP"
    assert len(result["critical_blockers"]) == 2


def test_decision_treats_short_and_long_equally():
    engine = DecisionEngine()
    for direction in ("LONG", "SHORT"):
        result = engine.decide(
            **_supportive_context(
                signal={"signal": direction, "confidence": 96, "grade": "S+", "strength": "ELITE"},
                risk={"entry": 100.0, "stop_loss": 101.0 if direction == "SHORT" else 99.0,
                      "rr": 3.5, "risk": 1.0, "position_size": 1.0, "weighted_net_rr": 3.0},
                mtf={"valid": True, "entry": direction},
                liquidity_sweep={
                    "is_sweep": True, "strength_score": 80,
                    "sell_side": direction == "LONG", "buy_side": direction == "SHORT",
                    "post_structure": {"confirmed": True,
                                       "direction": "BULLISH" if direction == "LONG" else "BEARISH"},
                },
                cisd={"active": True, "direction": "BEARISH" if direction == "SHORT" else "BULLISH",
                      "confidence": 80},
                volume_profile={"active": True, "direction": "BEARISH" if direction == "SHORT" else "BULLISH",
                                "confidence": 80},
                unicorn={"active": True, "direction": "BEARISH" if direction == "SHORT" else "BULLISH",
                         "best": {"direction": "BEARISH" if direction == "SHORT" else "BULLISH"},
                         "confidence": 80},
                smt={"active": True, "direction": direction, "confidence": 80},
                trade_quality={"allowed": True, "blockers": []},
            )
        )
        assert result["action"] == "EXECUTE", direction
        assert result["signal"] == direction
