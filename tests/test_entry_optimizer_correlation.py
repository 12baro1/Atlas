from entry_optimizer import EntryOptimizer


def test_correlation_counterpressure_moves_entry_deeper_without_blocking():
    entry = {
        "valid": True,
        "direction": "LONG",
        "entry": 100.0,
        "stop_loss": 85.0,
        "entry_type": "LIMIT",
        "poi_zone": {"low": 90.0, "high": 110.0},
    }
    result = EntryOptimizer().optimize(
        entry,
        current_price=120.0,
        correlation={
            "active": True,
            "trade_allowed": True,
            "counterpressure": True,
            "counterpressure_score": 1.0,
        },
    )
    assert result["applied"] is True
    assert any(item["source"] == "correlation" for item in result["evidence"])
    assert entry["entry"] < 100.0
    assert entry["confirmation_profile"]["counterpressure_reasons"] == ["correlation_counterpressure"]
