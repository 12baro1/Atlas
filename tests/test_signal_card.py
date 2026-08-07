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
    assert "->  AL" in text
    assert "67000" in text
    assert "TP1/2/3" in text


def test_card_no_raise_on_missing_keys():
    card = build_signal_card({"symbol": "X/USDT:USDT", "signal": {}, "decision": {}, "risk": None, "analysis": {}})
    assert card["verdict"] in ("ATLA", "BEKLE")