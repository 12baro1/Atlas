import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from entry_engine import EntryEngine
from engine import _tp1_already_reached


def test_short_setup_is_stale_when_price_has_crossed_tp1():
    assert _tp1_already_reached("SHORT", 100.45, 101.37) is True


def test_short_setup_is_not_stale_before_tp1():
    assert _tp1_already_reached("SHORT", 101.50, 101.37) is False


def test_long_setup_is_stale_when_price_has_crossed_tp1():
    assert _tp1_already_reached("LONG", 102.0, 101.37) is True


def test_invalid_numeric_tp_does_not_crash():
    assert _tp1_already_reached("SHORT", 100.0, None) is False


def test_long_rejects_stop_loss_above_entry():
    result = EntryEngine().generate(
        {"entry": "LONG"},
        [{"label": "HH", "price": 110, "kind": "HIGH"}],
        [],
        [{"low": 105.0, "high": 104.0, "type": "BULLISH", "filled": False, "mitigated": False}],
        current_price=103.0,
    )
    assert result["valid"] is False
    assert "stop-loss must be below entry" in result["reason"]


def test_short_rejects_stop_loss_below_entry():
    result = EntryEngine().generate(
        {"entry": "SHORT"},
        [{"label": "LL", "price": 90, "kind": "LOW"}],
        [],
        [{"low": 105.0, "high": 104.0, "type": "BEARISH", "filled": False, "mitigated": False}],
        current_price=106.0,
    )
    assert result["valid"] is False
    assert "stop-loss must be above entry" in result["reason"]


def test_signal_card_displays_recommended_entry_type():
    from utils.signal_card import build_signal_card, format_card_text

    card = build_signal_card({
        "symbol": "BTC/USDT:USDT",
        "signal": {"signal": "SHORT", "confidence": 80},
        "decision": {"action": "EXECUTE"},
        "risk": {"entry": 100.0, "stop_loss": 102.0, "tp1": 96.0},
        "rr": {"rr": 2.0},
        "analysis": {"entry": {"entry": 100.0, "entry_type": "LIMIT"}},
    })
    assert card["entry_type"] == "LIMIT"
    assert "Emir türü  : LIMIT" in format_card_text(card)
