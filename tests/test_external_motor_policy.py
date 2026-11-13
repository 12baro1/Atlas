"""Regression tests for operational hard gates owned by AtlasMainEngine."""

from atlas_main_engine import AtlasMainEngine


def _main():
    main = object.__new__(AtlasMainEngine)
    main.last_motor_report = {}
    return main


def test_correlation_counterpressure_warns_but_does_not_veto():
    result = _main().apply_operational_gates(
        {"action": "EXECUTE", "critical_blockers": []},
        news_filter={"active": True, "trade_allowed": True},
        correlation={"active": True, "trade_allowed": False, "reason": "BTC correlation conflict"},
        cooldown={"active": True, "trade_allowed": True},
    )
    assert result["action"] == "EXECUTE"
    assert result["critical_blockers"] == []
    assert any("correlation" in item for item in result["external_warnings"])


def test_inactive_correlation_data_does_not_veto_or_warn():
    result = _main().apply_operational_gates(
        {"action": "EXECUTE"},
        news_filter={},
        correlation={"active": False, "trade_allowed": False, "reason": "no peer data"},
        cooldown={},
    )
    assert result["action"] == "EXECUTE"
    assert "external_warnings" not in result


def test_macro_news_remains_a_hard_gate():
    result = _main().apply_operational_gates(
        {"action": "EXECUTE", "critical_blockers": []},
        news_filter={"active": True, "trade_allowed": False, "reason": "high impact event"},
        correlation={"active": True, "trade_allowed": True},
        cooldown={"active": True, "trade_allowed": True},
    )
    assert result["action"] == "SKIP"
    assert any("news_filter" in item for item in result["critical_blockers"])


def test_cooldown_remains_a_hard_duplicate_entry_gate():
    result = _main().apply_operational_gates(
        {"action": "EXECUTE", "critical_blockers": []},
        news_filter={"active": True, "trade_allowed": True},
        correlation={"active": True, "trade_allowed": True},
        cooldown={"active": True, "trade_allowed": False, "reason": "duplicate open position"},
    )
    assert result["action"] == "SKIP"
    assert any("cooldown" in item for item in result["critical_blockers"])
