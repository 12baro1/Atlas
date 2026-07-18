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


def test_backtest_monte_carlo_and_walk_forward_outputs():
    engine = BacktestEngine()

    for index in range(12):
        engine.record(
            {
                "result": "WIN" if index % 3 != 0 else "LOSS",
                "rr": 1.0 + (index % 4) * 0.5,
                "tp": (index % 3) + 1,
                "side": "LONG" if index % 2 == 0 else "SHORT",
            }
        )

    monte_carlo = engine.monte_carlo(iterations=64, sample_size=6)
    walk_forward = engine.walk_forward(window=6, step=3)
    analytics = engine.trade_analytics()

    assert monte_carlo["iterations"] > 0
    assert walk_forward["windows"]
    assert analytics["total"] == 12
    assert analytics["profit_factor"] >= 0
