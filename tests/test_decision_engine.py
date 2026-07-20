import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decision_engine import DecisionEngine


def _supportive_context(**overrides):
    context = {
        "signal": {"signal": "LONG", "confidence": 96, "grade": "S+", "strength": "ELITE"},
        "confluence": {"score": 82, "checks": ["✔ Stack Confluence (Sweep+OB+FVG+SMT+Phase)"]},
        "entry": {"valid": True},
        "risk": {"entry": 100.0, "stop_loss": 99.0, "rr": 3.5, "risk": 1.0, "position_size": 1.0},
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
    }
    context.update(overrides)
    return context


def test_decision_executes_for_strong_quality_setup():
    engine = DecisionEngine()

    result = engine.decide(**_supportive_context())

    assert result["action"] == "EXECUTE"
    assert "Decision Score:" in result["reason"]
    assert "+10 Grade S+" in result["reason"]
    assert "+10 ELITE" in result["reason"]
    assert "+10 Confidence >=95" in result["reason"]
    assert "+10 RR >=3" in result["reason"]
    assert "Final Action: EXECUTE" in result["reason"]


def test_decision_executes_with_caution_when_one_soft_blocker_remains():
    engine = DecisionEngine()

    result = engine.decide(
        **_supportive_context(
            signal={"signal": "LONG", "confidence": 95, "grade": "S+", "strength": "STRONG"},
            confluence={"score": 80, "checks": ["✔ Stack Confluence (Sweep+OB+FVG+SMT+Phase)"]},
            risk={"entry": 100.0, "stop_loss": 99.0, "rr": 3.0, "risk": 1.0, "position_size": 1.0},
            cisd={"active": True, "direction": "BULLISH", "confidence": 80},
            volume_profile={"active": True, "direction": "BEARISH", "confidence": 85},
            institutional={"active": True, "direction": "SHORT", "confidence": 80},
            unicorn={"active": True, "direction": "BEARISH", "best": {"direction": "BEARISH"}, "confidence": 80},
            ote={"valid": False},
            htf_orderblock={"valid": False},
            smt={"active": False, "direction": "NONE", "confidence": 0},
            liquidity_sweep={"is_sweep": False, "strength_score": 0},
            market_phase={"phase": "Expansion"},
        )
    )

    assert result["action"] == "EXECUTE_WITH_CAUTION"
    assert "-10 Unicorn mismatch" in result["reason"]
    assert "-8 Volume Profile mismatch" in result["reason"]
    assert "-10 Institutional mismatch" in result["reason"]
    assert "Final Action: EXECUTE_WITH_CAUTION" in result["reason"]


def test_decision_skips_when_entry_invalid_even_if_score_high():
    engine = DecisionEngine()

    result = engine.decide(
        **_supportive_context(
            entry={"valid": False},
            signal={"signal": "SHORT", "confidence": 100, "grade": "S+", "strength": "ELITE"},
            cisd={"active": True, "direction": "BEARISH", "confidence": 90},
            volume_profile={"active": True, "direction": "BEARISH", "confidence": 90},
            unicorn={"active": True, "direction": "BEARISH", "best": {"direction": "BEARISH"}, "confidence": 90},
            smt={"active": True, "direction": "SHORT", "confidence": 90},
        )
    )

    assert result["entry_valid"] is False
    assert result["action"] == "SKIP"
    assert "Entry invalid" in result["reason"]


def test_decision_skips_when_rr_below_minimum_threshold():
    engine = DecisionEngine()

    result = engine.decide(
        **_supportive_context(
            signal={"signal": "SHORT", "confidence": 100, "grade": "S+", "strength": "ELITE"},
            confluence={"score": 100, "checks": ["✔ Stack Confluence (Sweep+OB+FVG+SMT+Phase)"]},
            risk={"entry": 0.03089, "stop_loss": 0.03098, "rr": 0.67, "risk": 0.00009, "position_size": 140147.9424},
            cisd={"active": True, "direction": "BEARISH", "confidence": 86},
            volume_profile={"active": True, "direction": "BEARISH", "confidence": 91},
            institutional={"active": True, "direction": "SHORT", "confidence": 63},
        )
    )

    assert result["action"] == "SKIP"
    assert "RR below minimum RR" in result["reason"]


def test_decision_recovers_from_zero_rr_using_tp_breakdown():
    engine = DecisionEngine()

    result = engine.decide(
        **_supportive_context(
            signal={"signal": "LONG", "confidence": 100, "grade": "S+", "strength": "ELITE"},
            confluence={"score": 100, "checks": ["✔ Stack Confluence (Sweep+OB+FVG+SMT+Phase)"]},
            risk={
                "entry": 0.012642,
                "stop_loss": 0.012623,
                "tp1": 0.012664,
                "tp2": 0.012680,
                "tp3": 0.012699,
                "rr": 0,
                "rr_by_tp": {"tp1": 1.16, "tp2": 2.0, "tp3": 3.0},
                "selected_tp": "tp3",
                "selected_rr": 3.0,
                "risk": 0.000019,
                "position_size": 1.0,
            },
            cisd={"active": True, "direction": "BULLISH", "confidence": 86},
            volume_profile={"active": True, "direction": "BULLISH", "confidence": 91},
            institutional={"active": True, "direction": "LONG", "confidence": 63},
        )
    )

    assert result["rr"] == pytest.approx(3.0)
    assert result["action"] == "EXECUTE"


def test_decision_override_executes_despite_single_mismatch_on_elite_setup():
    engine = DecisionEngine()

    result = engine.decide(
        **_supportive_context(
            signal={"signal": "LONG", "confidence": 100, "grade": "S+", "strength": "ELITE"},
            confluence={"score": 84, "checks": ["✔ Stack Confluence (Sweep+OB+FVG+SMT+Phase)"]},
            risk={"entry": 100.0, "stop_loss": 99.0, "rr": 3.4, "risk": 1.0, "position_size": 1.0},
            unicorn={"active": True, "direction": "BEARISH", "best": {"direction": "BEARISH"}, "confidence": 92},
            cisd={"active": True, "direction": "BULLISH", "confidence": 85},
            volume_profile={"active": True, "direction": "LONG", "confidence": 88},
            market_phase={"phase": "Expansion"},
        )
    )

    assert result["action"] == "EXECUTE"
    assert "Override: high-quality mismatch exception met" in result["reason"]
    assert "-10 Unicorn mismatch" in result["reason"]


def test_decision_skips_when_grade_below_quality_floor():
    engine = DecisionEngine()

    result = engine.decide(
        **_supportive_context(
            signal={"signal": "LONG", "confidence": 99, "grade": "A+", "strength": "ELITE"},
            confluence={"score": 98, "checks": ["✔ Stack Confluence (Sweep+OB+FVG+SMT+Phase)"]},
            risk={"entry": 100.0, "stop_loss": 99.0, "rr": 4.1, "risk": 1.0, "position_size": 1.0},
            cisd={"active": True, "direction": "BULLISH", "confidence": 90},
            market_phase={"phase": "Expansion"},
        )
    )

    assert result["action"] == "SKIP"
    assert "Grade below quality minimum" in result["reason"]
