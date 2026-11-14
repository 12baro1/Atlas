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
    assert report["performance_status"] == "INSUFFICIENT_STRATEGY_SPECIFIC_OUTCOME_DATA"


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
    report = SevenStrategyLab().analyze({"symbol": "ETH/USDT:USDT"})

    assert report["selected"]["strategy_id"] == "trend_pullback"
    assert report["selected"]["entry"] == 200.0
    assert report["selected"]["stop_loss"] == 204.0
    assert report["selected"]["tp1"] == 195.0
    assert report["selected"]["reasons"] == ["trend only"]
