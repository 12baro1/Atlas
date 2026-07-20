import sys
import os
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
    assert risk["position_size"] == round(expected_target_capital, 4)
    assert risk["rr"] == 4.0


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
