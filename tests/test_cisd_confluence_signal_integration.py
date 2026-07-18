import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from confluence_engine import ConfluenceEngine
from signal_engine import SignalEngine


def test_confluence_and_signal_include_cisd():
    confluence = ConfluenceEngine().evaluate(
        mtf={"valid": True},
        trend={"trend": "BULLISH"},
        entry={"direction": "LONG", "valid": True},
        confirmation={"confirmed": True},
        premium_discount={"valid": True},
        liquidity_sweep={"is_sweep": True, "strength_score": 82},
        ote={"valid": True},
        htf_orderblock={"valid": True},
        htf_fvg={"valid": True},
        killzone=True,
        session=True,
        breaker=[{"breaker": True}],
        smt={"active": True, "direction": "BULLISH", "confidence": 80},
        orderblocks=[{"type": "BULLISH"}],
        fvg=[{"type": "BULLISH"}],
        market_phase={"phase": "Expansion"},
        unicorn={"active": False, "confidence": 0},
        cisd={"active": True, "direction": "BULLISH", "confidence": 77},
    )

    assert any("CISD" in item for item in confluence["checks"])

    signal = SignalEngine().generate(
        {
            "entry": {"direction": "LONG"},
            "confluence": confluence,
            "market_phase": {"phase": "Expansion", "phase_score": 88, "phase_confidence": 80, "mtf_alignment": 100},
            "liquidity_sweep": {"is_sweep": True, "strength_score": 82, "post_structure": {"confirmed": True}},
            "smt": {"active": True, "confidence": 80},
            "unicorn": {"active": False, "confidence": 0},
            "cisd": {"active": True, "direction": "BULLISH", "confidence": 77},
        }
    )

    assert signal["cisd_active"] is True
    assert signal["cisd_confidence"] == 77
    assert signal["cisd_direction"] == "BULLISH"
