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
