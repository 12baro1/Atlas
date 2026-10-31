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
    assert risk["capital_at_risk_target"] < round(expected_target_capital, 2)
    assert risk["weighted_rr"] == pytest.approx((1.5 + 2.5 + 4.0) / 3)
    assert risk["weighted_net_rr"] == pytest.approx(risk["weighted_rr"] - 0.2)
    assert risk["partial_exit_weights"] == pytest.approx({"tp1": 1/3, "tp2": 1/3, "tp3": 1/3})
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
    monkeypatch.setattr(Config, "AUTO_EXPAND_TIGHT_STOPS", True)
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
    assert risk["stop_loss"] == pytest.approx(80.50)
    assert risk["risk"] == pytest.approx(1.5)
    assert risk["rr"] == pytest.approx(1.0)


def test_risk_engine_auto_expands_tight_stop_even_when_reject_on(monkeypatch):
    # AUTO_EXPAND_TIGHT_STOPS (default True) önceliklidir: REJECT_TIGHT_STOPS açık
    # olsa bile sıkı stoplar otomatik genişletilir ve sinyal SKIP edilmez.
    monkeypatch.setattr(Config, "REJECT_TIGHT_STOPS", True)
    monkeypatch.setattr(Config, "AUTO_EXPAND_TIGHT_STOPS", True)
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
    assert risk["stop_loss"] == pytest.approx(80.50)
    assert risk["risk"] == pytest.approx(1.5)
    assert risk["rr"] == pytest.approx(1.0)
    assert risk["position_size"] > 0


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


def test_rr_engine_rejects_wrong_side_tp():
    engine = RREngine()
    assert engine.calculate_rr(10.0, 9.0, 9.5) is None, "LONG icin entry altinda TP gecersiz"
    assert engine.calculate_rr(10.0, 11.0, 10.5) is None, "SHORT icin entry ustunde TP gecersiz"
    assert engine.calculate_rr(10.0, 9.0, 11.0) == 1.0
    assert engine.calculate_rr(10.0, 11.0, 9.0) == 1.0


def test_dynamic_tp_never_emits_duplicate_levels():
    for direction, entry, sl, liq in [
        ("LONG", 10.0, 9.0, [{"price": 11.0}, {"price": 13.0}]),
        ("SHORT", 10.0, 11.0, [{"price": 9.0}, {"price": 7.0}]),
        ("LONG", 1.23456, 1.2335, [{"price": 1.2347}, {"price": 1.2351}, {"price": 1.2359}]),
    ]:
        r = DynamicTPEngine().calculate(
            direction=direction,
            entry=entry,
            stop_loss=sl,
            liquidity=liq,
            fvg=[],
            orderblocks=[],
            structure=[],
        )
        tp1, tp2, tp3 = r["tp1"], r["tp2"], r["tp3"]
        assert len({tp1, tp2, tp3}) == 3, f"{direction}: duplicate TP levels {tp1},{tp2},{tp3}"
        by_distance = sorted([tp1, tp2, tp3], key=lambda p: abs(p - entry))
        assert by_distance == [tp1, tp2, tp3], f"{direction}: TP order wrong"


def test_dynamic_tp_long_sl_behind_entry_rejected():
    r = DynamicTPEngine().calculate(
        direction="LONG",
        entry=10.0,
        stop_loss=9.0,
        liquidity=[{"price": 11.0}],
        fvg=[],
        orderblocks=[],
        structure=[],
    )
    tps = [r["tp1"], r["tp2"], r["tp3"]]
    assert r["tp1"] == 11.0
    assert all(tp > 10.0 for tp in tps), f"LONG TP'leri entry altina dusemez: {tps}"




def test_dynamic_tp_and_rr_recalculate_for_wider_structural_stop():
    engine = DynamicTPEngine()
    targets = [{"price": 102.0}, {"price": 104.0}, {"price": 106.0}]
    original = engine.calculate(
        direction="LONG", entry=100.0, stop_loss=99.0,
        liquidity=targets, fvg=[], orderblocks=[], structure=[],
        allow_rr_fallback=False,
    )
    widened = engine.calculate(
        direction="LONG", entry=100.0, stop_loss=98.0,
        liquidity=targets, fvg=[], orderblocks=[], structure=[],
        allow_rr_fallback=False,
    )
    original_risk = RiskEngine().calculate(
        entry=100.0, stop_loss=99.0, dynamic_tp=original,
        atr_value=0.0, spread=0.0, slippage=0.0,
    )
    widened_risk = RiskEngine().calculate(
        entry=100.0, stop_loss=98.0, dynamic_tp=widened,
        atr_value=0.0, spread=0.0, slippage=0.0,
    )

    assert original["tp1"] == pytest.approx(102.0)
    assert widened["tp1"] == pytest.approx(102.0)
    assert original_risk["rr"] == pytest.approx(6.0)
    assert widened_risk["rr"] == pytest.approx(3.0)
    assert widened_risk["risk"] == pytest.approx(2.0)



def test_risk_engine_rejects_non_finite_or_non_positive_entry_levels():
    engine = RiskEngine()
    assert engine.calculate(float("nan"), 99.0, dynamic_tp={"tp1": 101.0}) is None
    assert engine.calculate(100.0, float("inf"), dynamic_tp={"tp1": 101.0}) is None
    assert engine.calculate(0.0, 99.0, dynamic_tp={"tp1": 101.0}) is None


def test_risk_engine_accepts_numeric_string_prices():
    risk = RiskEngine().calculate(
        "100.0", "99.0",
        dynamic_tp={"tp1": 101.0, "tp2": 102.0, "tp3": 103.0},
    )
    assert risk is not None
    assert risk["side"] == "LONG"



def test_risk_engine_calculates_weighted_rr_for_equal_partial_exits(monkeypatch):
    monkeypatch.setattr(Config, "SIGNAL_OUTCOME_PARTIAL_WEIGHTS", "1.0,1.0,1.0")
    risk = RiskEngine().calculate(
        entry=100.0,
        stop_loss=99.0,
        dynamic_tp={"tp1": 101.0, "tp2": 102.0, "tp3": 103.0},
        atr_value=0.0,
        spread=0.0,
        slippage=0.0,
    )

    assert risk["rr"] == pytest.approx(3.0)  # highest single target stays explicit
    assert risk["target_max_rr"] == pytest.approx(3.0)
    assert risk["weighted_rr"] == pytest.approx(2.0)
    assert risk["weighted_net_rr"] == pytest.approx(1.8)
    assert risk["net_rr"] == pytest.approx(1.8)

    report = RREngine().evaluate(risk)
    assert report["rr"] == pytest.approx(2.0)
    assert report["selected_rr"] == pytest.approx(2.0)
    assert report["selected_tp"] == "weighted_partial_exit"
    assert report["target_max_tp"] == "tp3"
    assert report["target_max_rr"] == pytest.approx(3.0)


def test_risk_engine_uses_configured_partial_weights(monkeypatch):
    monkeypatch.setattr(Config, "SIGNAL_OUTCOME_PARTIAL_WEIGHTS", "0.5,0.3,0.2")
    risk = RiskEngine().calculate(
        entry=100.0,
        stop_loss=99.0,
        dynamic_tp={"tp1": 101.0, "tp2": 102.0, "tp3": 103.0},
        atr_value=0.0,
        spread=0.0,
        slippage=0.0,
    )

    assert risk["partial_exit_weights"] == pytest.approx({
        "tp1": 0.5, "tp2": 0.3, "tp3": 0.2
    })
    assert risk["weighted_rr"] == pytest.approx(1.7)
    assert risk["weighted_net_rr"] == pytest.approx(1.5)


def test_risk_engine_normalizes_weights_only_over_valid_targets(monkeypatch):
    monkeypatch.setattr(Config, "SIGNAL_OUTCOME_PARTIAL_WEIGHTS", "1,1,1")
    risk = RiskEngine().calculate(
        entry=100.0,
        stop_loss=99.0,
        dynamic_tp={"tp1": 101.0, "tp2": None, "tp3": 103.0},
        atr_value=0.0,
        spread=0.0,
        slippage=0.0,
    )

    assert risk["partial_exit_weights"] == pytest.approx({"tp1": 0.5, "tp3": 0.5})
    assert risk["weighted_rr"] == pytest.approx(2.0)
