from strategy_lab import SevenStrategyLab, _valid_plan


class Candle:
    def __init__(self, open_, high, low, close, volume=100.0):
        self.open = open_
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume


def test_lab_always_reports_all_seven_strategies():
    report = SevenStrategyLab().analyze({"symbol": "BTC/USDT:USDT", "15m": [], "1h": [], "4h": []})

    assert len(report["strategies"]) == 7
    assert {item["strategy_id"] for item in report["strategies"]} == {
        "trend_pullback", "volatility_breakout", "mean_reversion",
        "liquidation_cascade", "orderflow_momentum", "relative_strength", "smc",
    }
    assert report["selected"] is None
    assert report["performance_status"] == "OBSERVATIONAL_ONLY_NOT_AN_ELIGIBILITY_GATE"


def test_plan_rejects_wrong_side_or_non_finite_geometry():
    candles = [Candle(100, 101, 99, 100)]
    assert _valid_plan("LONG", 100, 101, 1, candles, "trend_pullback", 70) is None
    assert _valid_plan("SHORT", 100, 99, 1, candles, "trend_pullback", 70) is None
    assert _valid_plan("LONG", float("nan"), 98, 1, candles, "trend_pullback", 70) is None


def test_plan_contains_consistent_directional_targets_and_r_multiples():
    candles = [Candle(100, 101, 99, 100)]
    long_plan = _valid_plan("LONG", 100, 98, 1, candles, "trend_pullback", 70)
    short_plan = _valid_plan("SHORT", 100, 102, 1, candles, "trend_pullback", 70)

    assert long_plan["stop_loss"] < long_plan["entry"] < long_plan["tp1"] < long_plan["tp2"] < long_plan["tp3"]
    assert short_plan["tp3"] < short_plan["tp2"] < short_plan["tp1"] < short_plan["entry"] < short_plan["stop_loss"]
    assert long_plan["rr_tp1"] == 2.0
    assert short_plan["rr_tp3"] == 4.0
    assert long_plan["experimental"] is True


def test_lab_isolates_strategy_errors_and_keeps_full_registry(monkeypatch):
    import strategy_lab

    monkeypatch.setattr(strategy_lab, "_trend_pullback", lambda data: (_ for _ in ()).throw(RuntimeError("boom")))
    report = SevenStrategyLab().analyze({"symbol": "ETH/USDT:USDT"})

    trend = next(item for item in report["strategies"] if item["strategy_id"] == "trend_pullback")
    assert trend["status"] == "ERROR"
    assert len(report["strategies"]) == 7


def test_smc_is_kept_as_independent_seventh_strategy(monkeypatch):
    import strategy_lab

    smc_plan = {
        "status": "CANDIDATE", "strategy_id": "smc",
        "strategy": strategy_lab.STRATEGY_NAMES["smc"], "direction": "LONG",
        "entry_type": "LIMIT", "entry": 100.0, "stop_loss": 98.0,
        "tp1": 102.0, "tp2": 104.0, "tp3": 106.0,
        "strength": 90.0, "experimental": False, "reasons": ["existing SMC"],
    }
    monkeypatch.setattr(strategy_lab, "_smc_candidate", lambda result: dict(smc_plan))
    monkeypatch.setattr(strategy_lab, "_risk_validate_candidate", lambda plan: {
        "eligible": True, "reason": None, "weighted_net_rr": 2.5,
        "risk_plan": {"final_geometry_reconciled": True, "risk_setup_valid": True,
                      "weighted_net_rr": 2.5, "weighted_rr": 2.7},
    })
    report = SevenStrategyLab().analyze({"symbol": "BTC/USDT:USDT"}, smc_result={"unchanged": True})

    smc = next(item for item in report["strategies"] if item["strategy_id"] == "smc")
    assert smc["status"] == "SELECTED"
    assert smc["entry"] == 100.0
    assert smc["experimental"] is False
    assert report["selected"] is smc


def test_selector_returns_one_original_candidate_without_mixing_levels(monkeypatch):
    import strategy_lab

    trend_plan = {
        "status": "CANDIDATE", "strategy_id": "trend_pullback",
        "strategy": strategy_lab.STRATEGY_NAMES["trend_pullback"], "direction": "SHORT",
        "entry_type": "MARKET", "entry": 200.0, "stop_loss": 204.0,
        "tp1": 192.0, "tp2": 188.0, "tp3": 184.0,
        "strength": 100.0, "experimental": True, "reasons": ["trend only"],
    }
    monkeypatch.setattr(strategy_lab, "_trend_pullback", lambda data: dict(trend_plan))
    monkeypatch.setattr(strategy_lab, "_regime", lambda data: {"label": "TREND", "trend": "BEARISH", "strength": 1.0})
    monkeypatch.setattr(strategy_lab, "_risk_validate_candidate", lambda plan: {
        "eligible": True, "reason": None, "weighted_net_rr": 2.5,
        "risk_plan": {"final_geometry_reconciled": True, "risk_setup_valid": True,
                      "weighted_net_rr": 2.5, "weighted_rr": 2.7},
    })
    validated = {
        "trend_pullback": {
            "is_trades": 120, "is_expectancy_r": 0.24, "is_profit_factor": 1.42,
            "is_expectancy_std_r": 0.8, "oos_trades": 40,
            "oos_expectancy_r": 0.16, "oos_profit_factor": 1.23,
        }
    }
    report = SevenStrategyLab().analyze(
        {"symbol": "ETH/USDT:USDT"}, performance_by_strategy=validated
    )

    assert report["selected"]["strategy_id"] == "trend_pullback"
    assert report["selected"]["entry"] == 200.0
    assert report["selected"]["stop_loss"] == 204.0
    assert report["selected"]["tp1"] == 192.0
    assert report["selected"]["reasons"] == ["trend only"]



def test_plan_rejects_fee_drag_that_erases_tp1_reward():
    candles = [Candle(100, 101, 99, 100)]
    # 0.01 price risk on a 100 price creates fees larger than the 1.25R target.
    assert _valid_plan("LONG", 100, 99.99, 0.01, candles, "trend_pullback", 70) is not None


def test_current_price_prefers_fresh_ticker_over_last_closed_candle():
    from strategy_lab import _current_price

    candles = [Candle(100, 102, 99, 101)]
    assert _current_price({"current_price": 103.5, "15m": candles}) == 103.5
    assert _current_price({"15m": candles}) == 101



def test_experimental_candidate_is_not_selected_without_validated_performance(monkeypatch):
    import strategy_lab

    candidate = {
        "status": "CANDIDATE", "strategy_id": "trend_pullback",
        "strategy": strategy_lab.STRATEGY_NAMES["trend_pullback"], "direction": "LONG",
        "entry_type": "MARKET", "entry": 100.0, "stop_loss": 98.0,
        "tp1": 102.5, "tp2": 104.0, "tp3": 106.0,
        "strength": 99.0, "experimental": True, "reasons": ["synthetic"],
    }
    monkeypatch.setattr(strategy_lab, "_trend_pullback", lambda data: dict(candidate))
    monkeypatch.setattr(strategy_lab, "_regime", lambda data: {"label": "TREND", "trend": "BULLISH", "strength": 1.0})
    monkeypatch.setattr(strategy_lab, "_risk_validate_candidate", lambda plan: {
        "eligible": True, "reason": None, "weighted_net_rr": 2.5,
        "risk_plan": {"final_geometry_reconciled": True, "risk_setup_valid": True,
                      "weighted_net_rr": 2.5, "weighted_rr": 2.7},
    })
    report = SevenStrategyLab().analyze({"symbol": "BTC/USDT:USDT"})

    assert report["candidate_count"] == 1
    assert report["selected"]["strategy_id"] == "trend_pullback"
    assert report["validated_candidate_count"] == 1
    trend = next(item for item in report["strategies"] if item["strategy_id"] == "trend_pullback")
    assert trend["status"] == "SELECTED"
    assert report["diagnostics"]["selected_strategy_id"] == "trend_pullback"



def test_plan_uses_opposing_swing_liquidity_when_three_levels_exist():
    highs = [101, 102, 103, 105, 103, 102, 104, 105, 108, 106, 105, 107, 108, 111, 109, 108, 107]
    candles = [Candle(100, high, 99, 101) for high in highs]
    plan = _valid_plan("LONG", 100, 98, 1, candles, "trend_pullback", 70)

    assert plan["target_model"] == "SWING_LIQUIDITY"
    assert plan["tp1"] == 105
    assert plan["tp2"] == 108
    assert plan["tp3"] == 111



def test_diagnostics_report_every_strategy_and_status_counts():
    report = SevenStrategyLab().analyze({"symbol": "BTC/USDT:USDT", "15m": [], "1h": [], "4h": []})

    diagnostics = report["diagnostics"]
    assert diagnostics["strategy_count"] == 7
    assert diagnostics["candidate_count"] == 0
    assert diagnostics["validated_candidate_count"] == 0
    assert diagnostics["selected_strategy_id"] is None
    assert len(diagnostics["strategies"]) == 7
    assert diagnostics["status_counts"] == {
        "INSUFFICIENT_HISTORY": 3,
        "MISSING_DATA": 3,
        "NO_SETUP": 1,
    }
    by_id = {item["strategy_id"]: item for item in report["strategies"]}
    assert "open_interest_timestamps_ms" in by_id["liquidation_cascade"]["reason"]
    assert "orderbook" in by_id["orderflow_momentum"]["reason"]
    assert "correlation_universe" in by_id["relative_strength"]["reason"]


def test_risk_rejection_is_visible_in_strategy_diagnostics(monkeypatch):
    import strategy_lab

    candidate = {
        "status": "CANDIDATE", "strategy_id": "trend_pullback",
        "strategy": strategy_lab.STRATEGY_NAMES["trend_pullback"], "direction": "LONG",
        "entry_type": "MARKET", "entry": 100.0, "stop_loss": 98.0,
        "tp1": 102.5, "tp2": 104.0, "tp3": 106.0,
        "strength": 99.0, "experimental": True, "reasons": ["test"],
    }
    monkeypatch.setattr(strategy_lab, "_trend_pullback", lambda data: dict(candidate))
    monkeypatch.setattr(strategy_lab, "_regime", lambda data: {"label": "TREND", "trend": "BULLISH", "strength": 1.0})
    monkeypatch.setattr(strategy_lab, "_risk_validate_candidate", lambda plan: {
        "eligible": False, "reason": "TEST_STOP_COST_REJECT", "weighted_net_rr": 0.5, "risk_plan": None
    })

    report = SevenStrategyLab().analyze({"symbol": "BTC/USDT:USDT"})
    trend = next(item for item in report["strategies"] if item["strategy_id"] == "trend_pullback")

    assert trend["status"] == "BLOCKED_COMMON_FILTER"
    assert trend["rejection_stage"] == "COMMON_FILTER"
    assert trend["rejection_reasons"] == ["TEST_STOP_COST_REJECT"]
    assert report["diagnostics"]["rejection_stage_counts"] == {"COMMON_FILTER": 1}


def test_smc_raw_setup_is_not_suppressed_by_legacy_decision_filters():
    import strategy_lab

    raw = {
        "analysis": {
            "entry": {
                "direction": "LONG", "entry_type": "LIMIT", "entry": 100.0,
                "stop_loss": 98.0, "valid": False,
                "setup_reasoning": {"thesis": "4H CHoCH + OTE + FVG"},
            },
            "setup_quality": {"score": 88},
        },
        "risk": {
            "entry": 100.0, "stop_loss": 98.0,
            "tp1": 104.0, "tp2": 106.0, "tp3": 108.0,
            "atr": 1.5, "partial_exit_weights": {"tp1": 0.5, "tp2": 0.3, "tp3": 0.2},
        },
        "dynamic_tp": {"tp1": 104.0, "tp2": 106.0, "tp3": 108.0},
        "signal": {"signal": "WAIT", "confidence": 88},
        "decision": {"action": "SKIP", "reason": "legacy filter rejected"},
    }

    candidate = strategy_lab._smc_candidate(raw)

    assert candidate is not None
    assert candidate["strategy_id"] == "smc"
    assert candidate["direction"] == "LONG"
    assert candidate["entry"] == 100.0
    assert candidate["status"] == "RAW_SETUP"
    assert "4H CHoCH + OTE + FVG" in candidate["reasons"]


def test_execution_distance_gate_is_shared_and_preserves_far_limit_plans(monkeypatch):
    import strategy_lab

    market_plan = {
        "direction": "LONG", "entry_type": "MARKET", "entry": 100.0,
        "stop_loss": 98.0, "tp1": 104.0, "tp2": 106.0, "tp3": 108.0,
        "strength": 80.0, "reasons": ["test"],
    }
    monkeypatch.setattr(strategy_lab, "_trend_pullback", lambda data: dict(market_plan))
    monkeypatch.setattr(strategy_lab, "_risk_validate_candidate", lambda plan: {
        "eligible": True, "reason": None, "weighted_net_rr": 2.5,
        "risk_plan": {"final_geometry_reconciled": True, "risk_setup_valid": True,
                      "weighted_net_rr": 2.5, "weighted_rr": 2.7},
    })
    report = SevenStrategyLab().analyze({"symbol": "BTC/USDT:USDT", "current_price": 1000.0})
    trend = next(item for item in report["strategies"] if item["strategy_id"] == "trend_pullback")
    assert trend["status"] == "BLOCKED_COMMON_FILTER"
    assert trend["rejection_reasons"] == ["MARKET_ENTRY_TOO_FAR"]

    limit_plan = dict(market_plan, entry_type="LIMIT")
    monkeypatch.setattr(strategy_lab, "_trend_pullback", lambda data: dict(limit_plan))
    report = SevenStrategyLab().analyze({"symbol": "BTC/USDT:USDT", "current_price": 1000.0})
    trend = next(item for item in report["strategies"] if item["strategy_id"] == "trend_pullback")
    assert trend["status"] == "SELECTED"
    assert trend["entry_type"] == "LIMIT"



def test_diagnostics_distinguish_missing_live_inputs_from_pattern_mismatch():
    from strategy_lab import SevenStrategyLab

    report = SevenStrategyLab().analyze({
        "symbol": "BTC/USDT:USDT",
        "15m": [Candle(100, 101, 99, 100) for _ in range(40)],
        "1h": [Candle(100, 101, 99, 100) for _ in range(60)],
        "4h": [Candle(100, 101, 99, 100) for _ in range(80)],
        "open_interest": [1000.0],
        "open_interest_timestamps_ms": [],
        "recent_trades": [],
        "orderbook": None,
        "correlation_universe": {},
    })
    by_id = {item["strategy_id"]: item for item in report["strategies"]}

    assert by_id["liquidation_cascade"]["status"] == "MISSING_DATA"
    assert "timestamped observations" in by_id["liquidation_cascade"]["reason"]
    assert by_id["orderflow_momentum"]["status"] == "MISSING_DATA"
    assert by_id["relative_strength"]["status"] == "MISSING_DATA"
