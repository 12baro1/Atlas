"""Regression coverage for theoretical MARKET entry repricing risk."""
from core.candle import Candle
from telegram_tracking import apply_bar, _market_entry_risk_valid


def _plan():
    return {
        "direction": "SHORT", "entry": 0.1522, "stop_loss": 0.1523,
        "tp1": 0.1485, "tp2": 0.1477, "tp3": 0.1466,
        "entry_reached": False, "opened_at": 1, "status": "PENDING",
        "payload": {"execution_costs": {"entry_type": "MARKET"}},
    }


def test_kaito_tight_stop_rejected_before_virtual_entry():
    plan = _plan()
    candle = Candle(60_000, 0.1522, 0.15225, 0.1521, 0.1522, 10)
    assert apply_bar(plan, candle, 60_000)
    assert plan["status"] == "ENTRY_REJECTED"
    assert plan["entry_reached"] is False
    assert plan["entry"] == 0.1522


def test_market_entry_with_reasonable_stop_is_accepted_by_guard():
    plan = _plan()
    plan["stop_loss"] = 0.1560
    assert _market_entry_risk_valid(plan, 0.1520)


def test_market_repricing_toward_stop_is_rejected():
    plan = _plan()
    plan["stop_loss"] = 0.1550
    assert not _market_entry_risk_valid(plan, 0.1549)
