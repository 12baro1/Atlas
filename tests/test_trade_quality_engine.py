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
        "risk": {
            "risk_setup_valid": True, "entry": 100.0, "stop_loss": 98.0,
            "tp1": 102.0, "tp2": 104.0, "tp3": 106.0, "stop_adjusted": False,
        },
        "current_price": 101.0,
        "candles": None,
    }


def evaluate(payload):
    return TradeQualityEngine().evaluate(**payload)


def test_valid_trend_pullback_passes_without_relying_on_score():
    result = evaluate(base_payload())
    assert result["allowed"] is True
    assert result["blockers"] == []


def test_explicit_mtf_entry_direction_conflict_is_blocked():
    payload = base_payload()
    payload["mtf"] = {
        "valid": True,
        "entry": "SHORT",
        "h4": "BULLISH",
        "entry_source": "H4_STRUCTURE",
    }
    result = evaluate(payload)
    assert result["allowed"] is False
    assert "Multi-timeframe direction is not aligned" in result["blockers"]


def test_opposing_liquidity_sweep_is_counter_evidence_not_veto():
    payload = base_payload()
    payload["liquidity_sweep"] = {
        "is_sweep": True,
        "buy_side": True,
        "sell_side": False,
        "post_structure": {"confirmed": True, "direction": "BEARISH"},
    }
    result = evaluate(payload)
    assert result["allowed"] is True
    assert any("sweep" in item.lower() for item in result["warnings"])


def test_range_requires_sell_side_sweep_and_bullish_reclaim_for_long():
    payload = base_payload()
    payload["market_regime"] = {"active": True, "regime": "RANGING", "directional_bias": "NEUTRAL"}
    payload["liquidity_sweep"] = {
        "is_sweep": True,
        "buy_side": False,
        "sell_side": True,
        "post_structure": {
            "confirmed": True, "type": "CHOCH", "direction": "BULLISH",
            "sweep_index": 10, "confirmation_index": 12,
        },
    }
    assert evaluate(payload)["allowed"] is True


def test_range_without_confirmed_edge_sweep_uses_entry_evidence():
    payload = base_payload()
    payload["market_regime"] = {"active": True, "regime": "RANGING", "directional_bias": "NEUTRAL"}
    result = evaluate(payload)
    assert result["allowed"] is True
    assert any("ranging regime" in item.lower() for item in result["warnings"])


def test_compression_requires_directional_breakout():
    payload = base_payload()
    payload["market_regime"] = {"active": True, "regime": "COMPRESSION", "directional_bias": "NEUTRAL"}
    payload["liquidity_sweep"] = {"is_breakout": True, "breakout_side": "BUY_SIDE"}
    assert evaluate(payload)["allowed"] is True
    payload["liquidity_sweep"]["breakout_side"] = "SELL_SIDE"
    assert evaluate(payload)["allowed"] is True


def test_countertrend_regime_is_advisory_when_primary_mtf_and_poi_are_valid():
    payload = base_payload()
    payload["market_regime"] = {"active": True, "regime": "TRENDING_DOWN", "directional_bias": "BEARISH"}
    assert evaluate(payload)["allowed"] is True
    payload["liquidity_sweep"] = {
        "is_sweep": True,
        "buy_side": False,
        "sell_side": True,
        "post_structure": {"confirmed": True, "type": "CHOCH", "direction": "BULLISH", "sweep_index": 10, "confirmation_index": 12},
        "sweep_index": 10,
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
    # stop_adjusted artık otomatik bir engel değildir; engine genişletilen stop ile
    # TP'yi yeniden hesaplar ve final geometry tutarlılığı doğrulanır.
    assert evaluate(payload)["allowed"] is True
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


def test_high_confidence_specialist_motor_conflict_is_advisory():
    payload = base_payload()
    payload["smt"] = {"active": True, "direction": "BEARISH", "confidence": 88}
    result = TradeQualityEngine().evaluate(**payload)
    assert result["allowed"] is True
    assert result["blockers"] == []
    assert any("SMT" in item for item in result["warnings"])


def test_specialist_conflict_does_not_override_structural_execution_blockers():
    payload = base_payload()
    payload["smt"] = {"active": True, "direction": "BEARISH", "confidence": 88}
    payload["confirmation"] = {"confirmed": False, "reason": "15m confirmation missing"}
    result = TradeQualityEngine().evaluate(**payload)
    assert result["allowed"] is True
    assert any("15m confirmation missing" in item for item in result["warnings"])
    assert any("SMT" in item for item in result["warnings"])


def test_negative_learning_history_changes_entry_quality_but_does_not_veto_by_itself():
    payload = base_payload()
    payload["setup_quality"] = {
        "learning": {"matched": True, "sample_count": 25, "expected_r": -0.15}
    }
    result = TradeQualityEngine().evaluate(**payload)
    assert result["allowed"] is True
    assert any("Learning history" in item for item in result["warnings"])



def test_trend_disagreement_is_entry_evidence_not_an_automatic_veto():
    payload = base_payload()
    payload["trend"] = {"trend": "BEARISH"}
    result = evaluate(payload)
    assert result["allowed"] is True
    assert any("Trend conflict" in item for item in result["warnings"])


def test_opposing_sweep_can_be_reclaimed_before_entry():
    payload = base_payload()
    payload["liquidity_sweep"] = {
        "is_sweep": True,
        "buy_side": True,
        "sell_side": False,
        "post_structure": {"confirmed": True, "type": "CHOCH", "direction": "BULLISH", "sweep_index": 10, "confirmation_index": 12},
        "sweep_index": 10,
    }
    result = evaluate(payload)
    assert result["allowed"] is True
    assert any("Sweep evidence opposes" in item for item in result["warnings"])



def test_confirmed_sweep_reversal_can_override_h4_conflict_when_mtf_entry_matches():
    payload = base_payload()
    payload["entry"]["direction_source"] = "CONFIRMED_SWEEP_REVERSAL"
    payload["mtf"] = {
        "valid": True, "entry": "LONG", "h4": "BEARISH",
        "entry_source": "CONFIRMED_15M_REVERSAL",
    }
    payload["trend"] = {"trend": "BEARISH"}
    payload["market_regime"] = {
        "active": True, "regime": "TRENDING_DOWN", "directional_bias": "BEARISH"
    }
    payload["liquidity_sweep"] = {
        "is_sweep": True, "sell_side": True, "buy_side": False,
        "sweep_side": "SELL_SIDE",
        "sweep_index": 10,
        "post_structure": {"confirmed": True, "type": "CHOCH", "direction": "BULLISH", "sweep_index": 10, "confirmation_index": 12},
    }
    result = evaluate(payload)
    assert result["allowed"] is True
    assert "Multi-timeframe direction is not aligned" not in result["blockers"]


def test_unconfirmed_countertrend_candidate_remains_blocked_by_mtf_conflict():
    payload = base_payload()
    payload["entry"]["direction_source"] = "CONFIRMED_SWEEP_REVERSAL"
    payload["mtf"] = {"valid": True, "entry": "SHORT"}
    payload["liquidity_sweep"] = {
        "is_sweep": True, "sell_side": True, "buy_side": False,
        "post_structure": {"confirmed": False, "direction": "BULLISH"},
    }
    result = evaluate(payload)
    assert result["allowed"] is False
    assert "Multi-timeframe direction is not aligned" in result["blockers"]


def test_tp_levels_in_same_liquidity_cluster_are_rejected():
    payload = base_payload()
    payload["dynamic_tp"]["tp1"] = 102.0
    payload["dynamic_tp"]["tp2"] = 102.2
    payload["dynamic_tp"]["tp3"] = 106.0
    result = evaluate(payload)
    assert result["allowed"] is False
    assert any("same liquidity cluster" in item.lower() for item in result["blockers"])


def test_tp_levels_with_separate_structural_spacing_pass():
    payload = base_payload()
    payload["dynamic_tp"]["tp1"] = 102.0
    payload["dynamic_tp"]["tp2"] = 104.0
    payload["dynamic_tp"]["tp3"] = 106.0
    assert evaluate(payload)["allowed"] is True


def test_multiple_high_confidence_specialist_conflicts_are_blocked():
    payload = base_payload()
    payload["smt"] = {"active": True, "direction": "BEARISH", "confidence": 88}
    payload["institutional"] = {"active": True, "direction": "SHORT", "confidence": 86}
    result = evaluate(payload)
    assert result["allowed"] is False
    assert any("yüksek-güvenli uzman motoru" in item.lower() for item in result["blockers"])


def test_single_high_confidence_conflict_remains_advisory():
    payload = base_payload()
    payload["smt"] = {"active": True, "direction": "BEARISH", "confidence": 88}
    result = evaluate(payload)
    assert result["allowed"] is True
    assert result["blockers"] == []
    assert any("SMT" in item for item in result["warnings"])


def test_risk_output_must_match_the_final_structural_stop_and_targets():
    payload = base_payload()
    payload["risk"]["stop_loss"] = 97.5
    result = evaluate(payload)
    assert result["allowed"] is False
    assert any("risk engine stop differs" in item.lower() for item in result["blockers"])

    payload = base_payload()
    payload["risk"]["tp2"] = 104.5
    result = evaluate(payload)
    assert result["allowed"] is False
    assert any("tp2 differs" in item.lower() for item in result["blockers"])
