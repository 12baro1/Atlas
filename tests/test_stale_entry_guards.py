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
    engine = EntryEngine()
    engine._structure_fallback_levels = lambda direction, structure: (100.0, 101.0)
    result = engine.generate(
        {"entry": "LONG"},
        [{"label": "HH", "price": 110, "kind": "HIGH"}],
        [],
        [],
        current_price=None,
    )
    assert result["valid"] is False
    assert "stop-loss must be below entry" in result["reason"]


def test_short_rejects_stop_loss_below_entry():
    engine = EntryEngine()
    engine._structure_fallback_levels = lambda direction, structure: (100.0, 99.0)
    result = engine.generate(
        {"entry": "SHORT"},
        [{"label": "LL", "price": 90, "kind": "LOW"}],
        [],
        [],
        current_price=None,
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


def test_signal_card_labels_synthetic_tp_targets():
    from utils.signal_card import build_signal_card, format_card_text

    card = build_signal_card({
        "symbol": "BTC/USDT:USDT",
        "signal": {"signal": "LONG", "confidence": 80},
        "decision": {"action": "EXECUTE"},
        "risk": {"entry": 100.0, "stop_loss": 99.0, "tp1": 101.0, "tp2": 102.0, "tp3": 103.0},
        "dynamic_tp": {"synthetic_targets": True},
        "rr": {"rr": 3.0},
        "analysis": {"entry": {"entry": 100.0, "entry_type": "LIMIT"}},
    })
    assert "TP1/2/3 (sentetik RR)" in format_card_text(card)



def test_terminal_card_uses_only_clear_no_entry_decision():
    from utils.signal_card import build_signal_card, format_card_text

    card = build_signal_card({
        "symbol": "BTC/USDT:USDT",
        "signal": {"signal": "WAIT", "confidence": 22},
        "decision": {"action": "SKIP", "reason": "No valid setup"},
        "risk": {},
        "analysis": {"entry": {"valid": False, "entry_type": "NONE"}},
    })
    output = format_card_text(card)
    assert "KARAR: İŞLEME GİRME" in output
    assert "Emir türü  : YOK (işlem açma)" in output
    assert "Sinyal WAIT" not in output
    assert "ATLA" not in output
    assert "BEKLE" not in output


def test_pending_limit_card_explains_conditional_limit_entry():
    from utils.signal_card import build_signal_card, format_card_text

    card = build_signal_card({
        "symbol": "BTC/USDT:USDT",
        "signal": {"signal": "WAIT", "confidence": 60},
        "decision": {"action": "SKIP", "reason": "Entry not confirmed"},
        "risk": {},
        "analysis": {
            "entry": {
                "valid": False,
                "entry_type": "LIMIT",
                "entry_type_reason": "wait for pullback",
            }
        },
    })
    output = format_card_text(card)
    assert "KARAR: ŞİMDİ GİRME" in output
    assert "EMİR: LIMIT (FİYAT GELİNCE)" in output
    assert "Emir türü  : LIMIT (fiyat bölgesine gelirse)" in output
    assert "Sinyal WAIT" not in output
