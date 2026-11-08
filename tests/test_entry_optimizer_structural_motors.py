from entry_optimizer import EntryOptimizer


def test_structural_motors_contribute_evidence_and_levels_to_shared_entry():
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
        current_index=100,
        trendline_sweep={"active": True, "direction": "SELL_SIDE"},
        ifvg=[{"type": "BEARISH", "from": 96.0, "to": 98.0, "inverted": True, "index": 98}],
        eqh_eql={"active": True, "eql": [{"price": 95.0, "indices": [90, 95]}], "eqh": []},
        internal_structure=[
            {"index": 96, "label": "HH"},
            {"index": 98, "label": "HL"},
        ],
        external_structure=[
            {"index": 97, "bos": True, "direction": "BULLISH"},
        ],
        breaker=[
            {"breaker": True, "type": "BULLISH", "index": 98, "break_index": 99, "low": 97.0, "high": 99.0},
        ],
    )
    sources = {item["source"] for item in result["evidence"]}
    assert result["applied"] is True
    assert {
        "trendline_sweep", "ifvg", "equal_eql",
        "internal_structure", "external_structure", "breaker",
        "ifvg_zone", "breaker_zone",
    }.issubset(sources)
    assert 90.0 <= entry["entry"] <= 110.0
