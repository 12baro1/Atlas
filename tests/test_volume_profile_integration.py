import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from confluence_engine import ConfluenceEngine
from decision_engine import DecisionEngine
from risk_engine import RiskEngine
from signal_engine import SignalEngine


def test_confluence_signal_risk_decision_with_volume_profile():
    volume_profile = {
        "active": True,
        "direction": "BULLISH",
        "confidence": 84,
        "best": {"state": "DISCOUNT", "timeframe": "1h"},
    }

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
        unicorn={"active": True, "confidence": 70, "best": {"direction": "BULLISH"}},
        cisd={"active": True, "direction": "BULLISH", "confidence": 77},
        volume_profile=volume_profile,
    )

    signal = SignalEngine().generate(
        {
            "entry": {"direction": "LONG"},
            "confluence": confluence,
            "market_phase": {"phase": "Expansion", "phase_score": 88, "phase_confidence": 80, "mtf_alignment": 100},
            "liquidity_sweep": {"is_sweep": True, "strength_score": 82, "post_structure": {"confirmed": True}},
            "smt": {"active": True, "confidence": 80},
            "unicorn": {"active": True, "confidence": 70, "best": {"direction": "BULLISH"}},
            "cisd": {"active": True, "direction": "BULLISH", "confidence": 77},
            "volume_profile": volume_profile,
        }
    )

    risk = RiskEngine().calculate(
        entry=100.0,
        stop_loss=99.0,
        dynamic_tp={"tp1": 101, "tp2": 102, "tp3": 104},
        volume_profile=volume_profile,
    )

    decision = DecisionEngine().decide(
        signal=signal,
        confluence=confluence,
        entry={"valid": True},
        risk=risk,
        cisd={"active": True, "direction": "BULLISH", "confidence": 77},
        volume_profile=volume_profile,
    )

    assert any("Volume Profile" in item for item in confluence["checks"])
    assert signal["volume_profile_confidence"] == 84
    assert risk["volume_profile_factor"] >= 1.0
    assert decision["volume_profile_match"] is True
