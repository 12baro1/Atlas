from core.candle import Candle
from execution_costs import adverse_funding_cost_r


def _candle(time, close):
    return Candle(time=time, open=close, high=close, low=close, close=close, volume=1.0)


def test_long_pays_positive_funding_using_settlement_candle_close():
    result = adverse_funding_cost_r(
        "LONG", 100.0, 10.0, 0, 900_000,
        candles=[_candle(0, 110.0)],
        funding_records=[{"timestamp": 900_000, "value": 0.001}],
    )
    assert result["funding_pnl_r"] == -0.011
    assert result["funding_cost_r"] == 0.011
    assert result["charged_events"] == 1


def test_short_pays_negative_funding_and_credits_are_ignored():
    short = adverse_funding_cost_r(
        "SHORT", 100.0, 10.0, 0, 900_000,
        candles=[_candle(0, 110.0)],
        funding_records=[{"timestamp": 900_000, "value": -0.001}],
    )
    long_credit = adverse_funding_cost_r(
        "LONG", 100.0, 10.0, 0, 900_000,
        candles=[_candle(0, 110.0)],
        funding_records=[{"timestamp": 900_000, "value": -0.001}],
    )
    assert short["funding_cost_r"] == 0.011
    assert long_credit["funding_cost_r"] == 0.0
    assert long_credit["charged_events"] == 0


def test_funding_uses_strict_entry_and_inclusive_exit_time_bounds():
    result = adverse_funding_cost_r(
        "LONG", 100.0, 10.0, 900_000, 2_700_000,
        candles=[_candle(900_000, 100.0), _candle(1_800_000, 105.0)],
        funding_records=[
            {"timestamp": 900_000, "value": 0.01},
            {"timestamp": 1_800_000, "value": 0.001},
            {"timestamp": 2_700_000, "value": 0.001},
            {"timestamp": 2_700_001, "value": 0.01},
        ],
    )
    assert result["charged_events"] == 2
    assert result["funding_cost_r"] == 0.021
