from microstructure_submotors import (
    beta_stability,
    cumulative_volume_delta,
    liquidation_events,
    relative_volume,
)


def test_cvd_uses_explicit_aggressor_notionals():
    result = cumulative_volume_delta([
        {"timestamp_ms": 1000, "buy_notional": 12, "sell_notional": 8},
        {"timestamp_ms": 2000, "buy_notional": 3, "sell_notional": 7},
    ])
    assert result["state"] == "AVAILABLE"
    assert result["net_delta"] == 0
    assert result["direction"] == "BALANCED"


def test_cvd_does_not_infer_missing_trade_sides():
    assert cumulative_volume_delta([{"timestamp_ms": 1, "buy_notional": 2}])["state"] == "INVALID_DATA"


def test_liquidation_feed_rejects_invalid_and_filters_stale():
    result = liquidation_events([
        {"timestamp_ms": 1000, "notional": 10, "side": "BUY"},
        {"timestamp_ms": 99000, "notional": 5, "side": "SELL"},
    ], now_ms=100000, max_age_ms=5000)
    assert result["state"] == "AVAILABLE"
    assert result["events"] == 1
    assert result["buy_liquidation_notional"] == 10


def test_missing_liquidation_feed_is_not_claimed_as_events():
    assert liquidation_events([])["state"] == "UNAVAILABLE"


def test_beta_stability_reports_regime_change():
    a = [0.01, 0.02, -0.01, 0.0] * 12
    b = [0.01, 0.02, -0.01, 0.0] * 12
    assert beta_stability(a, b, 12)["state"] == "STABLE"


def test_relative_volume_requires_real_history():
    assert relative_volume(100, [100] * 5)["state"] == "UNAVAILABLE"
    assert relative_volume(200, [100] * 10)["state"] == "NORMAL"
