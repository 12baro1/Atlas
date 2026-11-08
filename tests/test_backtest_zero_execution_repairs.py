import pytest

from config import Config
from dynamic_tp_engine import DynamicTPEngine
from risk_engine import RiskEngine
from trade_quality_engine import TradeQualityEngine


def _quality_payload():
    return {
        "entry": {
            "valid": True,
            "direction": "LONG",
            "entry": 100.0,
            "stop_loss": 98.0,
            "entry_type": "LIMIT",
            "ote_confluence": True,
            "poi_source": "FVG",
            "poi_zone": {"low": 99.0, "high": 100.0},
        },
        "confirmation": {"confirmed": True},
        "mtf": {"valid": True, "entry": "LONG"},
        "trend": {"trend": "BULLISH"},
        "liquidity_sweep": {"is_sweep": False, "buy_side": False, "sell_side": False},
        "ote": {"valid": False, "fib62": 101.0, "fib79": 99.0},
        "market_regime": {"active": True, "regime": "TRENDING_UP", "directional_bias": "BULLISH"},
        "dynamic_tp": {
            "tp1": 102.0, "tp2": 104.0, "tp3": 106.0,
            "sources": ["market_structure"] * 3,
            "synthetic_targets": False,
        },
        "risk": {"risk_setup_valid": True, "stop_loss": 98.0, "stop_adjusted": False},
        "current_price": 100.0,
        "candles": None,
    }


def test_transition_allows_aligned_confirmed_poi_pullback_without_new_sweep():
    payload = _quality_payload()
    payload["market_regime"] = {
        "active": True, "regime": "TRANSITION", "directional_bias": "BULLISH"
    }
    result = TradeQualityEngine().evaluate(**payload)
    assert result["allowed"] is True


def test_transition_keeps_valid_poi_when_15m_confirmation_is_missing():
    payload = _quality_payload()
    payload["market_regime"] = {
        "active": True, "regime": "TRANSITION", "directional_bias": "BULLISH"
    }
    payload["confirmation"] = {"confirmed": False}
    result = TradeQualityEngine().evaluate(**payload)
    assert result["allowed"] is True
    assert any("Transition regime" in item for item in result["warnings"])


def test_cost_adjusted_net_rr_is_a_hard_gate(monkeypatch):
    payload = _quality_payload()
    payload["risk"]["weighted_net_rr"] = 1.2
    monkeypatch.setattr(Config, "MINIMUM_NET_RR", 1.5, raising=False)
    result = TradeQualityEngine().evaluate(**payload)
    assert result["allowed"] is False
    assert any("Cost-adjusted net RR" in item for item in result["blockers"])


def test_limit_percent_distance_is_advisory_when_atr_is_unavailable():
    payload = _quality_payload()
    payload["entry"]["entry"] = 106.0
    payload["current_price"] = 100.0
    payload["dynamic_tp"].update({"tp1": 114.8, "tp2": 122.8, "tp3": 131.6})
    result = TradeQualityEngine().evaluate(**payload)
    assert result["allowed"] is True
    assert any("LIMIT entry is far" in item for item in result["warnings"])


def test_structural_tp_selection_uses_risk_distance_not_atr_multiple():
    result = DynamicTPEngine().calculate(
        direction="LONG",
        entry=100.0,
        stop_loss=99.0,
        liquidity=[
            {"type": "BUY_SIDE", "price": 102.0},
            {"type": "BUY_SIDE", "price": 103.0},
            {"type": "BUY_SIDE", "price": 104.0},
        ],
        fvg=[],
        orderblocks=[],
        structure=[],
        atr_value=100.0,
        allow_rr_fallback=False,
    )
    assert result["tp1"] == pytest.approx(102.0)
    assert result["tp2"] == pytest.approx(103.0)
    assert result["tp3"] == pytest.approx(104.0)
    assert result["sources"] == ["market_structure"] * 3
    assert result["synthetic_targets"] is False


def test_stop_floor_does_not_add_spread_and_slippage_to_structural_distance(monkeypatch):
    monkeypatch.setattr(Config, "MIN_STOP_ATR_MULTIPLIER", 0.05)
    monkeypatch.setattr(Config, "MIN_STOP_PERCENT", 0.0001)
    monkeypatch.setattr(Config, "AUTO_EXPAND_TIGHT_STOPS", False)
    monkeypatch.setattr(Config, "REJECT_TIGHT_STOPS", True)
    result = RiskEngine().calculate(
        entry=100000.0,
        stop_loss=99980.0,
        dynamic_tp=None,
        atr_value=100.0,
        tick_size=0.01,
    )
    assert result["risk_setup_valid"] is True
    assert result["stop_adjusted"] is False
    assert result["minimum_stop_distance"] == pytest.approx(10.0)
    assert result["stop_loss"] == pytest.approx(99980.0)
