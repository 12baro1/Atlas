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
            "candidate_signals": 3, "unfilled_limits": 1, "open_trades": 1,
            "invalid_candidates": 0, "no_followup_data": 0,
            "tp1": 1, "tp2": 0, "tp3": 0,
        }),
        ("ETH", {
            "total": 2, "wins": 1, "net_rr": -0.5,
            "gross_profit_rr": 1.0, "gross_loss_rr": 1.5,
            "candidate_signals": 4, "unfilled_limits": 2, "open_trades": 0,
            "invalid_candidates": 1, "no_followup_data": 0,
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
    assert combined["candidate_signals"] == 7
    assert combined["unfilled_limits"] == 3
    assert combined["open_trades"] == 1
    assert combined["invalid_candidates"] == 1


def test_combined_stats_aggregate_historical_funding_cost_and_quality():
    combined = _combine_stats([
        ("BTC", {
            "total": 1, "wins": 1, "net_rr": 1.0, "gross_rr": 1.2,
            "gross_profit_rr": 1.2, "gross_loss_rr": 0.0,
            "total_funding_cost_r": 0.1, "funding_events_charged": 2,
            "funding_data_quality": {"funding": "HISTORICAL", "open_interest": "UNAVAILABLE"},
            "microstructure_data_quality": {"analysis_samples": 10, "archived_snapshots": 2, "orderbook_snapshots": 1, "trade_snapshots": 2},
            "trade_history": [{"gross_rr": 1.2, "net_rr": 1.0, "funding_cost_r": 0.1}],
        }),
        ("ETH", {
            "total": 1, "wins": 0, "net_rr": -1.0, "gross_rr": -0.8,
            "gross_profit_rr": 0.0, "gross_loss_rr": 0.8,
            "total_funding_cost_r": 0.2, "funding_events_charged": 3,
            "funding_data_quality": {"funding": "UNAVAILABLE", "open_interest": "UNAVAILABLE"},
            "microstructure_data_quality": {"analysis_samples": 5, "archived_snapshots": 3, "orderbook_snapshots": 2, "trade_snapshots": 3},
            "trade_history": [{"gross_rr": -0.8, "net_rr": -1.0, "funding_cost_r": 0.2}],
        }),
    ])
    assert combined["total_funding_cost_r"] == 0.3
    assert combined["funding_events_charged"] == 5
    assert combined["funding_data_quality"]["funding"].startswith("MIXED:")
    assert combined["funding_data_quality"]["open_interest"] == "UNAVAILABLE"
    assert combined["microstructure_data_quality"]["analysis_samples"] == 15
    assert combined["microstructure_data_quality"]["archived_snapshots"] == 5
    assert combined["microstructure_data_quality"]["snapshot_coverage_pct"] == 33.33
    assert combined["segment_breakdown"]["entry_type"]["UNKNOWN"]["funding_cost_r"] == 0.3
