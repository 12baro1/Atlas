import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decision_engine import DecisionEngine


def test_decision_long_when_cisd_aligned():
    engine = DecisionEngine()

    result = engine.decide(
        signal={"signal": "LONG", "confidence": 82},
        confluence={"score": 90},
        entry={"valid": True},
        risk={"risk": 1.2},
        cisd={"active": True, "direction": "BULLISH", "confidence": 78},
    )

    assert result["action"] == "LONG"
    assert result["cisd_match"] is True


def test_decision_wait_on_cisd_mismatch():
    engine = DecisionEngine()

    result = engine.decide(
        signal={"signal": "LONG", "confidence": 85},
        confluence={"score": 88},
        entry={"valid": True},
        risk={"risk": 1.0},
        cisd={"active": True, "direction": "BEARISH", "confidence": 80},
    )

    assert result["action"] == "WAIT"
    assert "mismatch" in result["reason"].lower()
