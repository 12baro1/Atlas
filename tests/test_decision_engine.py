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


def test_decision_wait_when_entry_invalid_even_if_score_high():
    engine = DecisionEngine()

    result = engine.decide(
        signal={"signal": "SHORT", "confidence": 100},
        confluence={"score": 100},
        entry={"valid": False},
        risk={"entry": 1.0, "stop_loss": 1.1, "rr": 3.2, "risk": 0.1},
        cisd={"active": True, "direction": "BEARISH", "confidence": 90},
        volume_profile={"active": True, "direction": "BEARISH", "confidence": 90},
        institutional={"active": True, "direction": "SHORT", "confidence": 90},
    )

    assert result["entry_valid"] is False
    assert result["action"] == "WAIT"
    assert "Entry is not valid" in result["reason"]


def test_decision_wait_when_risk_rr_exists_but_levels_missing():
    engine = DecisionEngine()

    result = engine.decide(
        signal={"signal": "LONG", "confidence": 95},
        confluence={"score": 95},
        entry={"valid": True},
        risk={"rr": 2.8},
        cisd={"active": True, "direction": "BULLISH", "confidence": 80},
    )

    assert result["risk_valid"] is False
    assert result["action"] == "WAIT"
    assert "Risk is not valid" in result["reason"]
