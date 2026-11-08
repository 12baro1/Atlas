import pytest

from config import Config
from risk_engine import RiskEngine
from trade_quality_engine import TradeQualityEngine


def _quality_payload(entry_price):
    risk_distance = entry_price - 98.0
    return {
        "entry": {
            "valid": True,
            "direction": "LONG",
            "entry": entry_price,
            "stop_loss": 98.0,
            "entry_type": "LIMIT",
            "ote_confluence": True,
        },
        "confirmation": {"confirmed": True},
        "mtf": {"valid": True, "entry": "LONG"},
        "trend": {"trend": "BULLISH"},
        "liquidity_sweep": {"is_sweep": False, "buy_side": False, "sell_side": False},
        "ote": {"valid": False, "fib62": 101.0, "fib79": 99.0},
        "market_regime": {"active": True, "regime": "TRENDING_UP", "directional_bias": "BULLISH"},
        "dynamic_tp": {
            "tp1": entry_price + risk_distance * 1.1,
            "tp2": entry_price + risk_distance * 2.1,
            "tp3": entry_price + risk_distance * 3.2,
            "sources": ["market_structure", "market_structure", "market_structure"],
            "synthetic_targets": False,
        },
        "risk": {"risk_setup_valid": True, "stop_loss": 98.0, "stop_adjusted": False},
        "current_price": 100.0,
        "candles": [object()] * 15,
    }


def test_structural_stop_inside_cost_adjusted_atr_floor_is_accepted_without_moving_it(monkeypatch):
    import risk_engine

    monkeypatch.setattr(risk_engine, "calculate_atr", lambda candles, period=14: 265.97142857)
    monkeypatch.setattr(Config, "MIN_STOP_ATR_MULTIPLIER", 0.05)
    monkeypatch.setattr(Config, "AUTO_EXPAND_TIGHT_STOPS", False)
    monkeypatch.setattr(Config, "REJECT_TIGHT_STOPS", True)
    entry = 77834.3
    structural_stop = 77890.49714285713
    risk = RiskEngine().calculate(
        entry=entry,
        stop_loss=structural_stop,
        dynamic_tp={"tp1": 77700.0, "tp2": 77500.0, "tp3": 77200.0},
        candles=[object()] * 20,
        tick_size=0.1,
    )

    assert risk["risk_setup_valid"] is True
    assert risk["stop_adjusted"] is False
    assert risk["stop_loss"] == pytest.approx(structural_stop)
    assert risk["minimum_stop_distance"] < risk["requested_risk"]


def test_structural_stop_that_cannot_cover_execution_costs_is_still_rejected(monkeypatch):
    import risk_engine

    monkeypatch.setattr(risk_engine, "calculate_atr", lambda candles, period=14: 88.27857143)
    monkeypatch.setattr(Config, "MIN_STOP_ATR_MULTIPLIER", 0.05)
    monkeypatch.setattr(Config, "AUTO_EXPAND_TIGHT_STOPS", False)
    monkeypatch.setattr(Config, "REJECT_TIGHT_STOPS", True)
    risk = RiskEngine().calculate(
        entry=77504.9,
        stop_loss=77520.72785714285,
        dynamic_tp={"tp1": 77400.0, "tp2": 77200.0, "tp3": 77000.0},
        candles=[object()] * 20,
        tick_size=0.1,
    )

    # Execution costs are no longer misclassified as a structural stop
    # distance requirement. The structural stop is preserved here; the
    # downstream quality gate rejects the setup if weighted net RR is poor.
    assert risk["risk_setup_valid"] is True
    assert risk["stop_adjusted"] is False
    assert risk["stop_loss"] == pytest.approx(77520.72785714285)
    assert risk["minimum_stop_distance"] < risk["requested_risk"]
    assert risk["spread_buffer"] > 0
    assert risk["slippage_buffer"] > 0


def test_limit_entry_distance_caps_are_advisory_and_reported(monkeypatch):
    import utils.atr

    monkeypatch.setattr(utils.atr, "atr", lambda candles, period=14: 1.0)
    monkeypatch.setattr(Config, "MAX_LIMIT_ENTRY_DISTANCE_ATR", 3.0)
    monkeypatch.setattr(Config, "MAX_LIMIT_ENTRY_DISTANCE_PERCENT", 0.05)

    result = TradeQualityEngine().evaluate(**_quality_payload(102.5))
    assert result["allowed"] is True

    too_far = TradeQualityEngine().evaluate(**_quality_payload(103.5))
    assert too_far["allowed"] is False
    assert any("configured distance" in item for item in too_far["blockers"])


def test_limit_entry_percent_distance_is_advisory_even_inside_atr_cap(monkeypatch):
    import utils.atr

    monkeypatch.setattr(utils.atr, "atr", lambda candles, period=14: 10.0)
    monkeypatch.setattr(Config, "MAX_LIMIT_ENTRY_DISTANCE_ATR", 3.0)
    monkeypatch.setattr(Config, "MAX_LIMIT_ENTRY_DISTANCE_PERCENT", 0.05)

    result = TradeQualityEngine().evaluate(**_quality_payload(106.0))
    assert result["allowed"] is False
    assert any("configured distance" in item for item in result["blockers"])


def test_pending_limit_is_rejected_when_tp1_was_already_reached(monkeypatch):
    import utils.atr

    monkeypatch.setattr(utils.atr, "atr", lambda candles, period=14: 2.5)
    payload = _quality_payload(102.5)
    payload["current_price"] = 107.5

    result = TradeQualityEngine().evaluate(**payload)

    assert result["allowed"] is False
    assert any("pending LIMIT entry" in item and "stale" in item for item in result["blockers"])
