import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from confluence_engine import ConfluenceEngine
from signal_engine import SignalEngine


def test_stack_confluence_bonus_and_signal_transfer():
    confluence_engine = ConfluenceEngine()

    confluence = confluence_engine.evaluate(
        mtf={"valid": True},
        trend={"trend": "BULLISH"},
        entry={"direction": "LONG", "valid": True},
        confirmation={"confirmed": True},
        premium_discount={"valid": True},
        liquidity_sweep={"is_sweep": True, "is_breakout": False, "strength_score": 88},
        ote={"valid": True},
        htf_orderblock={"valid": True},
        htf_fvg={"valid": True},
        killzone=True,
        session=True,
        breaker=[{"breaker": True}],
        smt={"active": True, "direction": "BULLISH", "confidence": 82},
        orderblocks=[{"type": "BULLISH"}],
        fvg=[{"type": "BULLISH"}],
        market_phase={"phase": "Expansion"},
    )

    assert confluence["score"] >= 100
    assert any("Stack Confluence" in item for item in confluence["checks"])

    signal = SignalEngine().generate(
        {
            "entry": {"direction": "LONG"},
            "confluence": confluence,
            "market_phase": {"phase": "Expansion", "phase_score": 90, "phase_confidence": 85, "mtf_alignment": 100},
            "liquidity_sweep": {"is_sweep": True, "strength_score": 88, "post_structure": {"confirmed": True}},
            "smt": {"active": True, "confidence": 82},
        }
    )

    assert signal["liquidity_strength"] == 88
    assert signal["smt_confidence"] == 82
    assert signal["confidence"] >= 78
    assert signal["grade"] in ["A", "A+", "S+"]
