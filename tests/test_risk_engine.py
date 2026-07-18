import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
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
