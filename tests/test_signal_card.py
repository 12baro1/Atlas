import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.signal_card import build_signal_card, format_card_text


def _result():
    return {
        "symbol": "BTC/USDT:USDT",
        "signal": {"signal": "LONG", "confidence": 95, "grade": "A+", "strength": "STRONG"},
        "decision": {
            "action": "EXECUTE",
            "confidence": 95,
            "critical_blockers": [],
            "quality_blockers": [],
            "soft_blockers": [{"label": "OTE missing", "delta": -5}],
            "bonuses": [{"label": "RR >=3", "delta": 10}],
            "reason": None,
        },
        "risk": {
            "entry": 67000,
            "stop_loss": 65800,
            "tp1": 69000,
            "tp2": 71000,
            "tp3": 73000,
            "rr": 4.0,
            "selected_tp": "tp3",
            "position_size": 100.0,
            "capital_at_risk": 60.0,
        },
        "rr": {"rr": 4.0},
        "dynamic_tp": {"tp1": 69000, "tp2": 71000, "tp3": 73000},
        "analysis": {
            "entry": {"valid": True, "entry": 67000, "stop_loss": 65800},
            "setup_quality": {"score": 82, "trade_allowed": True},
            "confluence": {"score": 92},
            "market_phase": {"phase": "Expansion"},
        },
    }


def _blocked_result():
    return {
        "symbol": "ETH/USDT:USDT",
        "signal": {"signal": "WAIT", "confidence": 40},
        "decision": {"action": "SKIP", "reason": "correlation block"},
        "risk": {},
        "analysis": {
            "entry": {},
            "setup_quality": {"score": 40, "trade_allowed": False},
            "confluence": {"score": 20},
            "market_phase": {"phase": "Konsolidasyon"},
        },
    }


def test_card_al_verdict_and_levels():
    card = build_signal_card(_result())
    assert card["verdict"] == "AL"
    assert card["direction"] == "LONG"
    assert card["entry"] == 67000.0
    assert card["stop_loss"] == 65800.0
    assert card["tp_levels"] == [69000.0, 71000.0, 73000.0]
    assert card["rr"] == 4.0
    assert card["selected_tp"] == "tp3"
    assert card["position_size"] == 100.0


def test_card_atla_verdict_and_blocks():
    card = build_signal_card(_blocked_result())
    assert card["verdict"] == "ATLA"
    assert card["direction"] is None
    assert card["entry"] is None
    assert "correlation block" in card["critical_blocks"]


def test_card_format_single_line_verdict():
    text = format_card_text(build_signal_card(_result()))
    assert "KARAR: İŞLEME GİR" in text
    assert "EMİR:" in text
    assert "67000" in text
    assert "TP1/2/3" in text


def test_card_no_raise_on_missing_keys():
    card = build_signal_card({"symbol": "X/USDT:USDT", "signal": {}, "decision": {}, "risk": None, "analysis": {}})
    assert card["verdict"] in ("ATLA", "BEKLE")
def test_signal_card_labels_confidence_as_score_not_probability():
    card = build_signal_card({
        "symbol": "BTC/USDT:USDT",
        "signal": {"signal": "WAIT", "confidence": 92},
        "decision": {"action": "WAIT", "reason": "No confirmed setup"},
        "risk": {},
        "analysis": {},
    })

    rendered = format_card_text(card)

    assert "skor 92/100" in rendered
    assert "92%" not in rendered


def test_pending_pullback_is_wait_not_invalid_signal():
    result = _blocked_result()
    result["decision"] = {
        "action": "SKIP",
        "reason": "Signal direction invalid; Entry invalid; Risk cannot be calculated; RR below quality minimum: None < 3",
        "critical_blockers": [
            "Signal direction invalid",
            "Entry invalid",
            "Risk cannot be calculated",
            "RR below quality minimum: None < 3",
            "OTE missing",
        ],
    }
    result["analysis"]["entry"] = {
        "valid": False,
        "entry": 79345.6,
        "stop_loss": 80265.7,
        "entry_type": "LIMIT",
        "entry_type_reason": "Wait for pullback to bearish POI",
    }

    card = build_signal_card(result)

    assert card["verdict"] == "BEKLE"
    assert card["direction"] is None
    assert card["entry"] == 79345.6
    assert "OTE missing" in card["critical_blocks"]
    assert "Signal direction invalid" not in card["critical_blocks"]
    assert "Entry invalid" not in card["critical_blocks"]
    assert "Risk cannot be calculated" not in card["critical_blocks"]
    assert not any(item.startswith("RR below quality minimum:") for item in card["critical_blocks"])
    assert "Wait for pullback to bearish POI" in card["critical_blocks"]


def test_market_trade_card_shows_clear_entry_permission():
    result = _result()
    result["analysis"]["entry"]["entry_type"] = "MARKET"
    rendered = format_card_text(build_signal_card(result))
    assert "KARAR: İŞLEME GİR | EMİR: MARKET" in rendered



def test_signal_card_preserves_small_coin_price_precision():
    result = _result()
    result["symbol"] = "ARB/USDT:USDT"
    result["signal"] = {"signal": "SHORT", "confidence": 90}
    result["decision"] = {"action": "EXECUTE", "critical_blockers": []}
    result["analysis"]["entry"] = {"entry": 0.173846, "entry_type": "LIMIT"}
    result["risk"] = {
        "entry": 0.173846,
        "stop_loss": 0.176214,
        "tp1": 0.171478,
        "tp2": 0.169110,
        "tp3": 0.166742,
        "rr": 3.0,
    }

    card = build_signal_card(result)

    assert card["entry"] == 0.173846
    assert card["stop_loss"] == 0.176214
    assert card["tp_levels"] == [0.171478, 0.169110, 0.166742]
    rendered = format_card_text(card)
    assert "0.173846" in rendered
    assert "0.176214" in rendered


def test_pending_limit_is_never_presented_as_immediate_entry_even_if_decision_executes():
    result = _result()
    result["decision"]["action"] = "EXECUTE"
    result["analysis"]["entry"].update({
        "entry_type": "LIMIT",
        "requires_pullback": True,
        "entry_type_reason": "Fiyatın LIMIT giriş bölgesine dönmesi gerekiyor",
    })
    rendered = format_card_text(build_signal_card(result))
    assert "KARAR: ŞİMDİ GİRME | EMİR: LIMIT (FİYAT GELİNCE)" in rendered
    assert "KARAR: İŞLEME GİR" not in rendered