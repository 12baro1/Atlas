import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest_engine import BacktestEngine


def test_backtest_statistics_include_profit_metrics():
    engine = BacktestEngine()

    engine.record({"result": "WIN", "rr": 2.0, "tp": 3})
    engine.record({"result": "LOSS", "rr": 1.0, "tp": 1})

    stats = engine.statistics()

    assert stats["total"] == 2
    assert stats["wins"] == 1
    assert stats["losses"] == 1
    assert stats["profit_factor"] >= 0
    assert stats["expectancy"] != 0


def test_backtest_reset_clears_state():
    engine = BacktestEngine()

    engine.record({"result": "WIN", "rr": 1.5, "tp": 2})
    engine.reset()

    stats = engine.statistics()

    assert stats["total"] == 0
    assert stats["winrate"] == 0
