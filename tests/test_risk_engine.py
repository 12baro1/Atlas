import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from dynamic_tp_engine import DynamicTPEngine
from rr_engine import RREngine
from risk_engine import RiskEngine


def test_risk_engine_uses_config_balance_and_percent():
    risk = RiskEngine().calculate(
        entry=100.0,
        stop_loss=99.0,
        dynamic_tp={"tp1": 101.5, "tp2": 102.5, "tp3": 104.0},
    )

    expected_target_capital = Config.INITIAL_BALANCE * (Config.RISK_PERCENT / 100)

    assert risk is not None
    assert risk["capital_at_risk_target"] == round(expected_target_capital, 2)
    assert risk["position_size"] > 0
    assert risk["position_size"] < round(expected_target_capital, 4)
    assert risk["effective_risk_per_unit"] > 1.0
    assert risk["rr"] == 4.0
    assert risk["selected_tp"] == "tp3"
    assert risk["selected_rr"] == 4.0
    assert risk["rr_by_tp"]["tp1"] == 1.5
    assert risk["rr_by_tp"]["tp2"] == 2.5
    assert risk["rr_by_tp"]["tp3"] == 4.0
    assert risk["rr1"] == 1.5
    assert risk["rr2"] == 2.5
    assert risk["rr3"] == 4.0


def test_risk_engine_reduces_risk_when_net_rr_is_weak():
    risk = RiskEngine().calculate(
        entry=100.0,
        stop_loss=99.0,
        dynamic_tp={"tp1": 100.5, "tp2": 101.0, "tp3": 101.5},
    )

    base_capital = Config.INITIAL_BALANCE * (Config.RISK_PERCENT / 100)

    assert risk is not None
    assert risk["rr"] == 1.5
    assert risk["net_rr"] is not None
    assert risk["net_rr"] < float(Config.MINIMUM_RR)
    assert risk["risk_percent"] < Config.RISK_PERCENT
    assert risk["capital_at_risk_target"] < round(base_capital, 2)


def test_dynamic_tp_engine_enforces_minimum_rr_levels_for_long():
    engine = DynamicTPEngine()

    result = engine.calculate(
        direction="LONG",
        entry=1.5769,
        stop_loss=1.5608,
        liquidity=[{"price": 1.5772}],
        fvg=[{"from": 1.5774, "to": 1.5776}],
        orderblocks=[{"high": 1.5787}],
    )

    risk = abs(1.5769 - 1.5608)

    assert result["tp1"] == pytest.approx(1.5769 + risk * 1.0)
    assert result["tp2"] == pytest.approx(1.5769 + risk * 2.0)
    assert result["tp3"] == pytest.approx(1.5769 + risk * 3.0)


def test_dynamic_tp_engine_enforces_minimum_rr_levels_for_short():
    engine = DynamicTPEngine()

    result = engine.calculate(
        direction="SHORT",
        entry=100.0,
        stop_loss=101.0,
        liquidity=[{"price": 99.9}],
        fvg=[{"from": 99.8, "to": 99.7}],
        orderblocks=[{"low": 99.6}],
    )

    assert result["tp1"] == pytest.approx(99.0)
    assert result["tp2"] == pytest.approx(98.0)
    assert result["tp3"] == pytest.approx(97.0)


def test_rr_engine_derives_rr_from_tp3_when_missing():
    dynamic_tp = DynamicTPEngine().calculate(
        direction="LONG",
        entry=100.0,
        stop_loss=99.0,
        liquidity=[],
        fvg=[],
        orderblocks=[],
    )

    risk = RiskEngine().calculate(
        entry=100.0,
        stop_loss=99.0,
        dynamic_tp=dynamic_tp,
    )

    assert risk is not None
    assert risk["rr"] == pytest.approx(3.0)

    rr = RREngine().evaluate({
        "entry": 100.0,
        "stop_loss": 99.0,
        "tp3": risk["tp3"],
    })

    assert rr is not None
    assert rr["rr"] == pytest.approx(3.0)
    assert rr["selected_tp"] == "tp3"
    assert rr["selected_rr"] == pytest.approx(3.0)
    assert rr["rr_by_tp"]["tp3"] == pytest.approx(3.0)


def test_rr_engine_uses_directional_formula_for_short_trade():
    rr = RREngine().calculate_breakdown(
        entry=0.03089,
        stop_loss=0.03098,
        tp1=0.03079,
        tp2=0.03069,
        tp3=0.03059,
    )

    assert rr is not None
    assert rr["direction"] == "SHORT"
    assert rr["rr_by_tp"]["tp1"] == pytest.approx(1.11, abs=0.01)
    assert rr["rr_by_tp"]["tp2"] == pytest.approx(2.22, abs=0.01)
    assert rr["rr_by_tp"]["tp3"] == pytest.approx(3.33, abs=0.01)
    assert rr["selected_tp"] == "tp3"
    assert rr["selected_rr"] == pytest.approx(3.33, abs=0.01)


def test_rr_engine_handles_real_long_example():
    rr = RREngine().calculate_breakdown(
        entry=0.012642,
        stop_loss=0.012623,
        tp1=0.012664,
        tp2=0.012680,
        tp3=0.012699,
    )

    assert rr is not None
    assert rr["direction"] == "LONG"
    assert rr["rr_by_tp"]["tp1"] == pytest.approx(1.16, abs=0.01)
    assert rr["rr_by_tp"]["tp2"] == pytest.approx(2.00, abs=0.01)
    assert rr["rr_by_tp"]["tp3"] == pytest.approx(3.00, abs=0.01)
    assert rr["selected_tp"] == "tp3"
    assert rr["selected_rr"] == pytest.approx(3.00, abs=0.01)


def test_rr_engine_recomputes_when_rr_is_zero():
    rr = RREngine().evaluate({
        "entry": 0.03089,
        "stop_loss": 0.03098,
        "tp1": 0.03079,
        "tp2": 0.03069,
        "tp3": 0.03059,
        "rr": 0,
    })

    assert rr is not None
    assert rr["rr"] == pytest.approx(3.33, abs=0.01)
    assert rr["selected_tp"] == "tp3"
    assert rr["selected_rr"] == pytest.approx(3.33, abs=0.01)


def test_risk_engine_expands_too_tight_stop_using_atr_floor(monkeypatch):
    # Sıkı stopları reddetme modu kapalıyken auto-expand davranışı korunur.
    monkeypatch.setattr(Config, "REJECT_TIGHT_STOPS", False)
    risk = RiskEngine().calculate(
        entry=79.00,
        stop_loss=79.01,
        dynamic_tp={"tp1": 78.5, "tp2": 78.0, "tp3": 77.5},
        atr_value=2.0,
        tick_size=0.01,
        spread=0.0,
        slippage=0.0,
    )

    assert risk is not None
    assert risk["risk_setup_valid"] is True
    assert risk["stop_adjusted"] is True
    assert risk["stop_loss"] == pytest.approx(79.50)
    assert risk["risk"] == pytest.approx(0.5)
    assert risk["rr"] == pytest.approx(3.0)


def test_risk_engine_rejects_too_tight_stop_by_default(monkeypatch):
    monkeypatch.setattr(Config, "REJECT_TIGHT_STOPS", True)
    risk = RiskEngine().calculate(
        entry=79.00,
        stop_loss=79.01,
        dynamic_tp={"tp1": 78.5, "tp2": 78.0, "tp3": 77.5},
        atr_value=2.0,
        tick_size=0.01,
        spread=0.0,
        slippage=0.0,
    )

    assert risk is not None
    assert risk["risk_setup_valid"] is False
    assert risk["risk_setup_reason"] == "Stop distance below minimum"


def test_risk_engine_uses_inferred_tick_for_micro_price_symbols(monkeypatch):
    monkeypatch.setattr(Config, "REJECT_TIGHT_STOPS", False)
    monkeypatch.setattr(Config, "MIN_TICK_DISTANCE_FALLBACK", 0.01)

    risk = RiskEngine().calculate(
        entry=0.02756,
        stop_loss=0.02758,
        dynamic_tp={"tp1": 0.0274, "tp2": 0.0273, "tp3": 0.02718},
        atr_value=0.0,
        spread=0.0,
        slippage=0.0,
    )

    assert risk is not None
    # Inferred precision from price should dominate configured 0.01 fallback.
    assert risk["tick_size"] == pytest.approx(0.00001)
    assert risk["minimum_stop_distance"] < 0.001


def test_risk_engine_caps_position_size_to_config_limit(monkeypatch):
    monkeypatch.setattr(Config, "MAX_POSITION_SIZE", 50.0)

    risk = RiskEngine().calculate(
        entry=100.0,
        stop_loss=99.0,
        dynamic_tp={"tp1": 101.5, "tp2": 102.5, "tp3": 104.0},
        atr_value=1.0,
        tick_size=0.01,
        spread=0.0,
        slippage=0.0,
    )

    assert risk is not None
    assert risk["position_size_raw"] > 50.0
    assert risk["position_size"] == pytest.approx(50.0)
    assert risk["position_size_capped"] is True
    assert risk["capital_at_risk"] == pytest.approx(50.0)


def test_risk_engine_marks_invalid_setup_when_auto_expand_disabled(monkeypatch):
    monkeypatch.setattr(Config, "AUTO_EXPAND_TIGHT_STOPS", False)
    monkeypatch.setattr(Config, "REJECT_TIGHT_STOPS", True)

    risk = RiskEngine().calculate(
        entry=79.00,
        stop_loss=79.01,
        dynamic_tp={"tp1": 78.5, "tp2": 78.0, "tp3": 77.5},
        atr_value=2.0,
        tick_size=0.01,
        spread=0.0,
        slippage=0.0,
    )

    assert risk is not None
    assert risk["risk_setup_valid"] is False
    assert risk["risk_setup_reason"] == "Invalid Risk Setup"
    assert risk["rr"] is None
