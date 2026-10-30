import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import importlib.util
from pathlib import Path

BACKTEST_SCRIPT = Path(__file__).resolve().parents[1] / "backtest.py"
spec = importlib.util.spec_from_file_location("atlas_backtest_cli", BACKTEST_SCRIPT)
backtest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backtest)
_combine_stats = backtest._combine_stats


def test_combined_profit_factor_uses_gross_wins_and_losses_not_net_symbol_totals():
    combined = _combine_stats([
        ("BTC", {
            "total": 2, "wins": 1, "net_rr": 1.0,
            "gross_profit_rr": 2.0, "gross_loss_rr": 1.0,
            "tp1": 1, "tp2": 0, "tp3": 0,
        }),
        ("ETH", {
            "total": 2, "wins": 1, "net_rr": -0.5,
            "gross_profit_rr": 1.0, "gross_loss_rr": 1.5,
            "tp1": 0, "tp2": 1, "tp3": 0,
        }),
    ])

    assert combined["total"] == 4
    assert combined["wins"] == 2
    assert combined["losses"] == 2
    assert combined["net_rr"] == 0.5
    assert combined["expectancy"] == 0.125
    assert combined["gross_profit_rr"] == 3.0
    assert combined["gross_loss_rr"] == 2.5
    assert combined["profit_factor"] == 1.2
