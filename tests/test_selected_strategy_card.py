from utils.signal_card import build_selected_strategy_card, format_card_text
from scanner_engine import ScannerEngine


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
        "tp1": 104.0,
        "tp2": 106.0,
        "tp3": 108.0,
        "strength": 78.0,
        "experimental": True,
        "target_model": "SWING_LIQUIDITY",
        "reasons": ["4H trend aligned", "1H pullback reclaimed"],
        "risk_validation": {"eligible": True, "weighted_net_rr": 2.5},
        "risk_plan": {
            "risk_setup_valid": True, "final_geometry_reconciled": True,
            "weighted_rr": 2.7, "weighted_net_rr": 2.5,
            "target_max_rr": 4.0, "partial_exit_weights": {"tp1": 0.5, "tp2": 0.3, "tp3": 0.2},
            "position_size": 5.0, "capital_at_risk": 10.0,
        },
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
    assert card["tp_levels"] == [104.0, 106.0, 108.0]
    assert card["strategy_id"] == "trend_pullback"
    rendered = format_card_text(card)
    assert "İŞLEME GİR" in rendered
    assert "Strateji  : Trend Following + Pullback" in rendered


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

def test_selected_short_plan_preserves_directional_price_geometry():
    card = build_selected_strategy_card(_result(_candidate(
        direction="SHORT", entry=100.0, stop_loss=102.0,
        tp1=96.0, tp2=94.0, tp3=92.0,
    )))
    assert card["direction"] == "SHORT"
    assert card["stop_loss"] > card["entry"] > card["tp_levels"][0]


def test_scanner_uses_selected_strategy_instead_of_smc_payload():
    result = _result(_candidate())
    scanner = ScannerEngine()
    scanner.add("BTC/USDT:USDT", result)
    row = scanner.results()[0]
    assert row["tradable"] is True
    assert row["strategy_id"] == "trend_pullback"
    assert row["direction"] == "LONG"
    assert row["entry"] == 100.0


def test_scanner_fails_closed_when_strategy_selection_is_missing():
    result = _result(None)
    result["signal"] = {"signal": "LONG"}
    result["decision"] = {"action": "EXECUTE"}
    result["risk"] = {"entry": 100, "stop_loss": 98, "tp1": 102, "tp2": 104, "tp3": 106, "risk_setup_valid": True}
    result["analysis"] = {"entry": {"entry": 100, "stop_loss": 98, "entry_type": "MARKET", "valid": True}}
    scanner = ScannerEngine()
    scanner.add("BTC/USDT:USDT", result)
    assert scanner.summary()["executable"] == []
