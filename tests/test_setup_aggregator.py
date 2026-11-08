from setup_aggregator import SetupAggregator


def test_aggregator_collects_aligned_and_opposing_motor_evidence_without_veto():
    result = SetupAggregator().aggregate(
        entry={"valid": True, "direction": "LONG", "entry": 100, "entry_type": "LIMIT"},
        mtf={"entry": "LONG"},
        confirmation={"confirmed": True},
        smt={"active": True, "direction": "BEARISH", "confidence": 80},
        cisd={"active": True, "direction": "BULLISH", "confidence": 75},
        trade_quality={"allowed": True},
    )
    assert result["structural_valid"] is True
    assert result["direction"] == "LONG"
    assert result["counter_count"] >= 1
    assert result["trade_quality_allowed"] is True
    assert result["scores"]["LONG"] != result["scores"]["SHORT"]


def test_aggregator_never_manufactures_trade_without_valid_structural_poi():
    result = SetupAggregator().aggregate(
        entry={"valid": False, "direction": "LONG", "entry": None},
        mtf={"entry": "LONG"},
        cisd={"active": True, "direction": "BULLISH", "confidence": 99},
    )
    assert result["structural_valid"] is False
    assert result["direction"] == "NONE"
    assert result["entry_price"] is None


def test_aggregator_preserves_optimizer_evidence_and_entry_plan():
    result = SetupAggregator().aggregate(
        entry={"valid": True, "direction": "SHORT", "entry": 99, "entry_type": "LIMIT"},
        mtf={"entry": "SHORT"},
        optimization={"applied": True, "evidence": [{"source": "ifvg", "bias": "ALIGNED", "weight": 1.2}]},
    )
    assert result["optimizer_applied"] is True
    assert result["entry_price"] == 99
    assert any(item["motor"] == "ifvg" for item in result["evidence"])


def _signal_input(consensus=None):
    payload = {
        "confluence": {"score": 80, "checks": []},
        "entry": {"valid": True, "direction": "LONG"},
        "confirmation": {"confirmed": True},
        "market_phase": {"phase": "Expansion", "phase_score": 50, "mtf_alignment": 50},
        "liquidity_sweep": {},
        "smt": {},
        "unicorn": {},
        "cisd": {},
        "volume_profile": {},
        "institutional": {},
        "setup_quality": {},
        "trade_quality": {},
    }
    if consensus is not None:
        payload["setup_consensus"] = consensus
    return payload


def test_signal_engine_uses_consensus_as_bounded_soft_adjustment():
    from signal_engine import SignalEngine

    engine = SignalEngine()
    baseline = engine.generate(_signal_input())
    aligned = engine.generate(_signal_input({
        "structural_valid": True, "direction": "LONG", "score": 100,
    }))
    opposed = engine.generate(_signal_input({
        "structural_valid": True, "direction": "LONG", "score": 0,
    }))

    assert aligned["setup_consensus_delta"] == 6.0
    assert opposed["setup_consensus_delta"] == -6.0
    assert aligned["confidence"] - baseline["confidence"] == 6
    assert baseline["signal"] == aligned["signal"] == opposed["signal"] == "LONG"


def test_signal_engine_does_not_apply_consensus_without_structural_setup():
    from signal_engine import SignalEngine

    result = SignalEngine().generate(_signal_input({
        "structural_valid": False, "direction": "NONE", "score": 100,
    }))
    assert result["setup_consensus_delta"] == 0.0
