from price_precision import snap_price_to_tick
from strategy_lab import _snap_candidate_to_exchange_tick


def test_decimal_tick_snapping_preserves_sub_eight_decimal_ticks():
    assert snap_price_to_tick(0.00000000037, 0.0000000001, "nearest") == 0.0000000004
    assert snap_price_to_tick(0.0673593664, 0.000001, "floor") == 0.067359
    assert snap_price_to_tick(0.0673593664, 0.000001, "ceiling") == 0.06736


def test_common_strategy_filter_snaps_long_geometry_outward():
    candidate = {
        "direction": "LONG",
        "entry_type": "LIMIT",
        "entry": 100.004,
        "stop_loss": 95.004,
        "tp1": 105.004,
        "tp2": 110.004,
        "tp3": 115.004,
    }
    _snap_candidate_to_exchange_tick(candidate, 0.01)
    assert candidate["entry"] == 100.0
    assert candidate["stop_loss"] == 95.0
    assert candidate["tp1"] == 105.01
    assert candidate["tp2"] == 110.01
    assert candidate["tp3"] == 115.01


def test_common_strategy_filter_snaps_short_geometry_outward():
    candidate = {
        "direction": "SHORT",
        "entry_type": "LIMIT",
        "entry": 100.004,
        "stop_loss": 105.004,
        "tp1": 95.004,
        "tp2": 90.004,
        "tp3": 85.004,
    }
    _snap_candidate_to_exchange_tick(candidate, 0.01)
    assert candidate["entry"] == 100.01
    assert candidate["stop_loss"] == 105.01
    assert candidate["tp1"] == 95.0
    assert candidate["tp2"] == 90.0
    assert candidate["tp3"] == 85.0



def test_gate_contract_fee_rates_flow_into_strategy_common_risk_filter():
    from risk_engine import RiskEngine
    from strategy_lab import _risk_validate_candidate

    candidate = {
        "entry": 100.0,
        "stop_loss": 98.0,
        "direction": "LONG",
        "entry_type": "MARKET",
        "tp1": 104.0,
        "tp2": 106.0,
        "tp3": 108.0,
        "atr": 1.0,
    }
    market_data = {"maker_fee_rate": 0.00013, "taker_fee_rate": 0.00072}
    validation = _risk_validate_candidate(candidate, market_data)
    assert validation["risk_plan"]["maker_fee_rate"] == 0.00013
    assert validation["risk_plan"]["taker_fee_rate"] == 0.00072

    risk = RiskEngine().calculate(
        entry=100.0,
        stop_loss=99.0,
        dynamic_tp={"tp1": 102.0, "tp2": 103.0, "tp3": 104.0},
        atr_value=0.0,
        maker_fee_rate=0.00013,
        taker_fee_rate=0.00072,
        spread=0.0,
        slippage=0.0,
    )
    assert risk["maker_fee_rate"] == 0.00013
    assert risk["taker_fee_rate"] == 0.00072
