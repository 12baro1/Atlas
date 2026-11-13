import pytest

from config import Config
from core.candle import Candle
from risk_engine import RiskEngine
from trade_quality_engine import TradeQualityEngine


def _candle_atr(atr=2.0, base=100.0, n=15):
    """Gerçek Candle nesneleriyle ATR≈2 üret (mock object yerine)."""
    return [
        Candle(time=1000 + i * 60, open=base + i, high=base + i + atr,
               low=base + i - atr, close=base + i + atr / 2, volume=1.0)
        for i in range(n)
    ]


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
        "candles": _candle_atr(),
    }


def test_structural_stop_inside_cost_adjusted_atr_floor_is_accepted_without_moving_it(monkeypatch):
    import risk_engine

    monkeypatch.setattr(risk_engine, "calculate_atr", lambda candles, period=14: 265.97142857)
    monkeypatch.setattr(Config, "MIN_STOP_ATR_MULTIPLIER", 0.05)
    monkeypatch.setattr(Config, "MAX_STOP_EXECUTION_COST_R", 10.0)
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

    # The structural stop remains untouched, but its modeled stop-exit
    # friction is far above the configured 0.50R execution budget.
    assert risk["risk_setup_valid"] is False
    assert risk["reason_code"] == "STOP_EXECUTION_COST_TOO_HIGH"
    assert risk["stop_loss"] == pytest.approx(77520.72785714285)
    assert risk["stop_execution_cost_r"] > risk["max_stop_execution_cost_r"]
    assert risk["spread_buffer"] > 0
    assert risk["slippage_buffer"] > 0


def test_limit_entry_distance_caps_are_advisory_and_reported(monkeypatch):
    import utils.atr

    # Stop 3.0 ATR'nin üstünde değil (entry=102.5, stop=98.0, atr=2.0 -> 2.25 ATR),
    # dolayısıyla stop kalitesi filtresi engel değildir; yalnızca uzak LIMIT
    # advisory olarak raporlanır.
    monkeypatch.setattr(utils.atr, "atr", lambda candles, period=14: 2.0)
    monkeypatch.setattr(Config, "QUALITY_MAX_ENTRY_DISTANCE_ATR", 1.0)
    monkeypatch.setattr(Config, "MAX_LIMIT_ENTRY_DISTANCE_ATR", 3.0)
    monkeypatch.setattr(Config, "MAX_LIMIT_ENTRY_DISTANCE_PERCENT", 0.05)

    result = TradeQualityEngine().evaluate(**_quality_payload(102.5))
    assert result["allowed"] is True

    too_far = TradeQualityEngine().evaluate(**_quality_payload(103.5))
    assert too_far["allowed"] is True
    assert any("LIMIT entry is far" in item for item in too_far["warnings"])


def test_limit_entry_percent_distance_is_advisory_even_inside_atr_cap(monkeypatch):
    import utils.atr

    monkeypatch.setattr(utils.atr, "atr", lambda candles, period=14: 10.0)
    monkeypatch.setattr(Config, "MAX_LIMIT_ENTRY_DISTANCE_ATR", 3.0)
    monkeypatch.setattr(Config, "MAX_LIMIT_ENTRY_DISTANCE_PERCENT", 0.05)

    result = TradeQualityEngine().evaluate(**_quality_payload(106.0))
    assert result["allowed"] is True
    assert any("LIMIT entry is far" in item for item in result["warnings"])


def test_pending_limit_is_rejected_when_tp1_was_already_reached(monkeypatch):
    import utils.atr

    monkeypatch.setattr(utils.atr, "atr", lambda candles, period=14: 2.5)
    payload = _quality_payload(102.5)
    payload["current_price"] = 107.5

    result = TradeQualityEngine().evaluate(**payload)

    assert result["allowed"] is False
    assert any("pending LIMIT entry" in item and "stale" in item for item in result["blockers"])



def test_poi_quality_rejects_entry_outside_explicit_poi_zone(monkeypatch):
    import utils.atr

    monkeypatch.setattr(utils.atr, "atr", lambda candles, period=14: 2.0)
    payload = _quality_payload(100.0)
    payload["entry"].update({
        "poi_source": "FVG",
        "poi_zone": {"low": 98.0, "high": 99.0},
        "ote_confluence": True,
        "structure_aligned": True,
    })

    result = TradeQualityEngine().evaluate(**payload)

    assert result["allowed"] is False
    assert any("POI quality: entry outside selected zone" in item for item in result["blockers"])


def test_poi_quality_accepts_valid_confluent_fvg_zone(monkeypatch):
    import utils.atr

    monkeypatch.setattr(utils.atr, "atr", lambda candles, period=14: 2.0)
    payload = _quality_payload(100.0)
    payload["entry"].update({
        "poi_source": "FVG",
        "poi_zone": {"low": 99.0, "high": 101.0},
        "ote_confluence": True,
        "structure_aligned": True,
    })

    result = TradeQualityEngine().evaluate(**payload)

    assert result["allowed"] is True
    assert result["setup_quality"]["quality_filters"]["filters"]["poi_quality"]["score"] >= 50


def test_stop_atr_quality_uses_final_structural_stop_floor(monkeypatch):
    import utils.atr

    monkeypatch.setattr(utils.atr, "atr", lambda candles, period=14: 2.0)
    monkeypatch.setattr(Config, "QUALITY_MIN_STOP_ATR", 0.25)
    monkeypatch.setattr(Config, "MIN_STOP_ATR_MULTIPLIER", 0.75)
    payload = _quality_payload(100.0)
    payload["entry"]["stop_loss"] = 99.2
    payload["risk"]["stop_loss"] = 99.2
    payload["dynamic_tp"].update({
        "tp1": 100.88,
        "tp2": 101.68,
        "tp3": 102.56,
    })

    result = TradeQualityEngine().evaluate(**payload)

    assert result["allowed"] is False
    assert any("Stop too tight" in item for item in result["blockers"])
