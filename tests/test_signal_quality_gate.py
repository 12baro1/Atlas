from signal_engine import SignalEngine


def _analysis():
    return {
        "confluence": {"score": 10, "checks": []},
        "entry": {"direction": "LONG", "entry": 100.0, "stop_loss": 98.0, "valid": True},
        "confirmation": {"confirmed": True},
        "market_phase": {"phase": "Expansion", "phase_confidence": 80, "phase_score": 80, "mtf_alignment": 100},
        "setup_quality": {"active": True, "score": 20, "trade_allowed": False},
        "trade_quality": {"allowed": True, "blockers": [], "reason": "All execution-quality checks passed"},
    }


def test_signal_engine_uses_cross_motor_gate_instead_of_setup_score_blocker():
    result = SignalEngine().generate(_analysis())
    assert result["signal"] == "LONG"


def test_signal_engine_preserves_direction_for_single_decision_authority_veto():
    analysis = _analysis()
    analysis["trade_quality"] = {
        "allowed": False,
        "blockers": ["Liquidity sweep direction conflicts with the trade"],
        "reason": "Liquidity sweep direction conflicts with the trade",
    }
    result = SignalEngine().generate(analysis)
    assert result["signal"] == "LONG"
    assert result["wait_reason"] is None
