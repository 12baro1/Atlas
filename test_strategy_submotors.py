from types import SimpleNamespace

from strategy_submotors import (
    breakout_acceptance,
    displacement,
    rsi_divergence,
    statistical_deviation,
    trend_structure,
    volatility_regime,
)


def bars(rows):
    return [SimpleNamespace(open=o, high=h, low=l, close=c, volume=100.0)
            for o, h, l, c in rows]


def test_displacement_reports_direction_and_normalized_impulse():
    result = displacement(bars([(10, 13, 9, 12.5)]), atr=2)
    assert result["direction"] == "BULLISH"
    assert result["body_atr"] == 1.25
    assert result["state"] == "IMPULSE"


def test_displacement_fails_closed_on_malformed_ohlc():
    result = displacement(bars([(10, 9, 11, 10.5)]), atr=1)
    assert result["state"] == "INVALID_DATA"


def test_breakout_acceptance_distinguishes_close_from_wick_sweep():
    inside = bars([(10, 11, 9, 10)] * 20 + [(10, 12, 9.5, 10.8)])
    failed = breakout_acceptance(inside, 20)
    assert failed["state"] == "FAILED_UPSIDE"
    accepted = bars([(10, 11, 9, 10)] * 20 + [(10, 12, 10, 11.5)])
    assert breakout_acceptance(accepted, 20)["state"] == "ACCEPTED"


def test_statistical_deviation_excludes_current_observation():
    result = statistical_deviation([1.0] * 20 + [5.0], 20)
    assert result["state"] == "EXTREME"
    assert result["zscore"] > 0


def test_trend_structure_returns_explicit_insufficient_history():
    assert trend_structure(bars([(10, 11, 9, 10)] * 8))["state"] == "UNKNOWN"


def test_volatility_regime_requires_sufficient_history():
    assert volatility_regime(bars([(10, 11, 9, 10)] * 10))["state"] == "UNAVAILABLE"


def test_rsi_divergence_handles_missing_alignment():
    assert rsi_divergence(bars([(10, 11, 9, 10)] * 12), [50.0] * 11)["state"] == "UNAVAILABLE"
