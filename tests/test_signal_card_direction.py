import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.signal_card import build_signal_card, format_card_text


def test_pending_limit_displays_entry_direction_when_signal_is_wait():
    card = build_signal_card({
        "symbol": "BNBUSDT",
        "signal": {"signal": "WAIT", "confidence": 0},
        "decision": {"action": "WAIT", "reason": "Pending limit entry"},
        "analysis": {
            "entry": {
                "direction": "SHORT",
                "entry": 610.0,
                "stop_loss": 620.0,
                "entry_type": "LIMIT",
                "entry_type_reason": "Fiyatın LIMIT bölgesine dönmesi gerekiyor",
            },
            "setup_quality": {},
            "confluence": {},
            "market_phase": {},
        },
        "risk": {"stop_loss": 620.0, "tp1": 600.0, "tp2": 590.0, "tp3": 580.0, "rr": 3.0},
        "dynamic_tp": {},
        "rr": {},
    })
    rendered = format_card_text(card)
    assert card["direction"] == "SHORT"
    assert "Yön        : SHORT" in rendered
    assert "ŞİMDİ GİRME" in rendered
