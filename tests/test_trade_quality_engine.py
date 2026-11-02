from trade_quality_engine import TradeQualityEngine


def base_payload():
    return {
        "entry": {
            "valid": True,
            "direction": "LONG",
            "entry": 100.0,
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
            "tp1": 102.0,
            "tp2": 104.0,
            "tp3": 106.0,
            "sources": ["market_structure", "market_structure", "market_structure"],
            "synthetic_targets": False,
        },
        "risk": {"risk_setup_valid": True, "stop_loss": 98.0, "stop_adjusted": False},
        "current_price": 101.0,
        "candles": None,
    }


def evaluate(payload):
    return TradeQualityEngine().evaluate(**payload)


def test_valid_trend_pullback_passes_without_relying_on_score():
    result = evaluate(base_payload())
    assert result["allowed"] is True
    assert result["blockers"] == []


def test_opposing_liquidity_sweep_blocks_trade():
    payload = base_payload()
    payload["liquidity_sweep"] = {
        "is_sweep": True,
        "buy_side": True,
        "sell_side": False,
        "post_structure": {"confirmed": True, "direction": "BEARISH"},
    }
    result = evaluate(payload)
    assert result["allowed"] is False
    assert any("sweep" in item.lower() for item in result["blockers"])


def test_range_requires_sell_side_sweep_and_bullish_reclaim_for_long():
    payload = base_payload()
    payload["market_regime"] = {"active": True, "regime": "RANGING", "directional_bias": "NEUTRAL"}
    payload["liquidity_sweep"] = {
        "is_sweep": True,
        "buy_side": False,
        "sell_side": True,
        "post_structure": {"confirmed": True, "direction": "BULLISH"},
    }
    assert evaluate(payload)["allowed"] is True


def test_range_without_confirmed_edge_sweep_is_blocked():
    payload = base_payload()
    payload["market_regime"] = {"active": True, "regime": "RANGING", "directional_bias": "NEUTRAL"}
    result = evaluate(payload)
    assert result["allowed"] is False
    assert any("range trade requires" in item.lower() for item in result["blockers"])


def test_compression_requires_directional_breakout():
    payload = base_payload()
    payload["market_regime"] = {"active": True, "regime": "COMPRESSION", "directional_bias": "NEUTRAL"}
    payload["liquidity_sweep"] = {"is_breakout": True, "breakout_side": "BUY_SIDE"}
    assert evaluate(payload)["allowed"] is True
    payload["liquidity_sweep"]["breakout_side"] = "SELL_SIDE"
    assert evaluate(payload)["allowed"] is False


def test_countertrend_trade_requires_confirmed_reversal_sweep():
    payload = base_payload()
    payload["market_regime"] = {"active": True, "regime": "TRENDING_DOWN", "directional_bias": "BEARISH"}
    assert evaluate(payload)["allowed"] is False
    payload["liquidity_sweep"] = {
        "is_sweep": True,
        "buy_side": False,
        "sell_side": True,
        "post_structure": {"confirmed": True, "direction": "BULLISH"},
    }
    assert evaluate(payload)["allowed"] is True


def test_synthetic_targets_are_rejected():
    payload = base_payload()
    payload["dynamic_tp"]["synthetic_targets"] = True
    result = evaluate(payload)
    assert result["allowed"] is False
    assert any("synthetic" in item.lower() for item in result["blockers"])


def test_invalid_or_adjusted_stop_is_rejected():
    payload = base_payload()
    payload["risk"]["stop_adjusted"] = True
    assert evaluate(payload)["allowed"] is False
    payload["risk"]["stop_adjusted"] = False
    payload["risk"]["risk_setup_valid"] = False
    assert evaluate(payload)["allowed"] is False


def test_tp_order_and_minimum_final_rr_are_hard_requirements():
    payload = base_payload()
    payload["dynamic_tp"]["tp2"] = 101.5
    assert evaluate(payload)["allowed"] is False
    payload = base_payload()
    payload["dynamic_tp"]["tp3"] = 104.0
    assert evaluate(payload)["allowed"] is False


def test_unknown_regime_is_warning_not_an_automatic_trade_block():
    payload = base_payload()
    payload["market_regime"] = {"active": False, "regime": "UNKNOWN"}
    result = evaluate(payload)
    assert result["allowed"] is True
    assert result["warnings"]
