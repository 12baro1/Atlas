import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.candle import Candle
from backtest_runner import simulate_trade, BacktestRunner


def _candle(t, o, h, l, cl):
    return Candle(time=t, open=o, high=h, low=l, close=cl, volume=1.0)


def _rising_series(n=800, start_price=100.0):
    return [
        _candle(1000 + i * 60, start_price + i, start_price + i + 2, start_price + i - 2, start_price + i + 1)
        for i in range(n)
    ]


def test_simulate_long_hits_tp1_before_unknown():
    candles = [_candle(1, 10.2, 11.0, 10.1, 11.0)]
    out = simulate_trade(10, 9, [11, 12, 13], candles, "LONG")
    assert out["result"] == "WIN"
    assert out["tp"] == 1
    assert out["net_rr"] == 1.0


def test_simulate_long_stop_loss_first():
    candles = [_candle(1, 10.0, 10.2, 8.5, 8.6)]
    out = simulate_trade(10, 9, [11, 12], candles, "LONG")
    assert out["result"] == "LOSS"
    assert out["tp"] == 0
    assert out["net_rr"] == -1.0


def test_simulate_short_hits_tp():
    candles = [_candle(1, 9.6, 10.0, 8.9, 9.0)]
    out = simulate_trade(10, 11, [9, 8], candles, "SHORT")
    assert out["result"] == "WIN"
    assert out["tp"] == 1


def test_simulate_no_touch_is_loss():
    candles = [_candle(1, 10.5, 10.6, 10.1, 10.2)]
    out = simulate_trade(10, 9, [12, 13], candles, "LONG")
    assert out["result"] == "LOSS"
    assert out["tp"] == 0


def test_runner_counts_and_reports_expectancy():
    candles = _rising_series(800)

    def fake_analyze(window):
        n = len(window["15m"])
        if n == 400:
            return {
                "decision": {"action": "EXECUTE"},
                "signal": {"signal": "LONG"},
                "risk": {"entry": 500.0, "stop_loss": 400.0, "tp1": 600.0, "tp2": 700.0, "tp3": 800.0},
            }
        return None

    runner = BacktestRunner(analyze_fn=fake_analyze)
    stats = runner.run({"15m": candles})
    assert stats["total"] == 1
    assert stats["wins"] == 1
    assert stats["winrate"] == 100.0
    assert stats["expectancy"] > 0
    assert stats["tp1"] == 1


def test_runner_ignores_skip_and_missing_risk():
    candles = _rising_series(500)

    def fake_analyze(window):
        n = len(window["15m"])
        if n == 400:
            # wait signal -> ignored
            return {"decision": {"action": "SKIP"}, "signal": {"signal": "WAIT"}, "risk": {}}
        return None

    runner = BacktestRunner(analyze_fn=fake_analyze)
    stats = runner.run({"15m": candles})
    assert stats["total"] == 0