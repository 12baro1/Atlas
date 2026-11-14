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
    assert report["performance_status"] == "NO_EXPERIMENTAL_EDGE_VALIDATED"


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
    assert long_plan["rr_tp1"] == 1.25
    assert short_plan["rr_tp3"] == 3.0
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
    report = SevenStrategyLab().analyze({"symbol": "BTC/USDT:USDT"}, smc_result={"unchanged": True})

    smc = next(item for item in report["strategies"] if item["strategy_id"] == "smc")
    assert smc["status"] == "CANDIDATE"
    assert smc["entry"] == 100.0
    assert smc["experimental"] is False
    assert report["selected"] is smc


def test_selector_returns_one_original_candidate_without_mixing_levels(monkeypatch):
    import strategy_lab

    trend_plan = {
        "status": "CANDIDATE", "strategy_id": "trend_pullback",
        "strategy": strategy_lab.STRATEGY_NAMES["trend_pullback"], "direction": "SHORT",
        "entry_type": "MARKET", "entry": 200.0, "stop_loss": 204.0,
        "tp1": 195.0, "tp2": 192.0, "tp3": 188.0,
        "strength": 100.0, "experimental": True, "reasons": ["trend only"],
    }
    monkeypatch.setattr(strategy_lab, "_trend_pullback", lambda data: dict(trend_plan))
    monkeypatch.setattr(strategy_lab, "_regime", lambda data: {"label": "TREND", "trend": "BEARISH", "strength": 1.0})
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
    assert report["selected"]["tp1"] == 195.0
    assert report["selected"]["reasons"] == ["trend only"]



def test_plan_rejects_fee_drag_that_erases_tp1_reward():
    candles = [Candle(100, 101, 99, 100)]
    # 0.01 price risk on a 100 price creates fees larger than the 1.25R target.
    assert _valid_plan("LONG", 100, 99.99, 0.01, candles, "trend_pullback", 70) is None


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
    report = SevenStrategyLab().analyze({"symbol": "BTC/USDT:USDT"})

    assert report["candidate_count"] == 1
    assert report["selected"] is None
    assert report["validated_candidate_count"] == 0
    trend = next(item for item in report["strategies"] if item["strategy_id"] == "trend_pullback")
    assert trend["edge_validation"]["eligible"] is False



def test_plan_uses_opposing_swing_liquidity_when_three_levels_exist():
    highs = [101, 102, 103, 105, 103, 102, 104, 105, 108, 106, 105, 107, 108, 111, 109, 108, 107]
    candles = [Candle(100, high, 99, 101) for high in highs]
    plan = _valid_plan("LONG", 100, 98, 1, candles, "trend_pullback", 70)

    assert plan["target_model"] == "SWING_LIQUIDITY"
    assert plan["tp1"] == 105
    assert plan["tp2"] == 108
    assert plan["tp3"] == 111
