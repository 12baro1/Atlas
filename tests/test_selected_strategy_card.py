from utils.signal_card import build_selected_strategy_card, format_card_text


def _result(selected):
    return {
        "symbol": "BTC/USDT:USDT",
        "signal": {"signal": "WAIT", "confidence": 20},
        "decision": {"action": "WAIT", "reason": "SMC has no executable setup"},
        "risk": {},
        "analysis": {},
        "strategy_lab": {
            "regime": {"label": "TREND", "trend": "BULLISH"},
            "candidate_count": 1,
            "selected": selected,
        },
    }


def _candidate(**overrides):
    payload = {
        "status": "CANDIDATE",
        "strategy_id": "trend_pullback",
        "strategy": "Trend Following + Pullback",
        "direction": "LONG",
        "entry_type": "MARKET",
        "entry": 100.0,
        "stop_loss": 98.0,
        "tp1": 102.5,
        "tp2": 104.0,
        "tp3": 106.0,
        "strength": 78.0,
        "experimental": True,
        "target_model": "SWING_LIQUIDITY",
        "reasons": ["4H trend aligned", "1H pullback reclaimed"],
    }
    payload.update(overrides)
    return payload


def test_selected_experimental_plan_becomes_executable_canonical_card():
    card = build_selected_strategy_card(_result(_candidate()))
    assert card["direction"] == "LONG"
    assert card["decision_action"] == "EXECUTE"
    assert card["entry_type"] == "MARKET"
    assert card["entry"] == 100.0
    assert card["stop_loss"] == 98.0
    assert card["tp_levels"] == [102.5, 104.0, 106.0]
    assert card["strategy_id"] == "trend_pullback"
    rendered = format_card_text(card)
    assert "İŞLEME GİR" in rendered
    assert "Trend Following + Pullback" in rendered


def test_selected_limit_plan_is_pending_not_immediate_entry():
    card = build_selected_strategy_card(_result(_candidate(entry_type="LIMIT")))
    rendered = format_card_text(card)
    assert card["verdict"] == "BEKLE"
    assert "LIMIT BEKLE" in rendered
    assert "KARAR: İŞLEME GİR" not in rendered


def test_invalid_selected_geometry_fails_closed():
    card = build_selected_strategy_card(_result(_candidate(stop_loss=101.0)))
    assert card["decision_action"] == "SKIP"
    assert card["direction"] is None
    assert card["entry"] is None
    assert "SELECTED_PLAN_GEOMETRY_INVALID" in card["critical_blocks"]


def test_missing_selected_plan_does_not_fall_back_to_smc_execute():
    result = _result(None)
    result["decision"] = {"action": "EXECUTE", "reason": "legacy SMC signal"}
    result["signal"] = {"signal": "LONG"}
    result["risk"] = {"entry": 100, "stop_loss": 98, "tp1": 102, "tp2": 104, "tp3": 106, "risk_setup_valid": True}
    result["analysis"] = {"entry": {"entry": 100, "stop_loss": 98, "entry_type": "MARKET", "valid": True}}
    card = build_selected_strategy_card(result)
    assert card["decision_action"] == "SKIP"
    assert card["direction"] is None
