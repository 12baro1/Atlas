from strategy_backtest import simulate_candidate, _snapshot_at
from backtest_runner import BacktestRunner
from backtest import _configured_partial_tp_weights


def candidate(direction="LONG", entry_type="MARKET"):
    if direction == "LONG":
        return {
            "direction": direction, "entry_type": entry_type,
            "entry": 100.0, "stop_loss": 98.0,
            "tp1": 102.5, "tp2": 104.0, "tp3": 106.0,
        }
    return {
        "direction": direction, "entry_type": entry_type,
        "entry": 100.0, "stop_loss": 102.0,
        "tp1": 97.5, "tp2": 96.0, "tp3": 94.0,
    }


class Bar:
    def __init__(self, open_, high, low, close, time=1_700_000_000_000):
        self.open = open_
        self.high = high
        self.low = low
        self.close = close
        self.time = time


def test_same_bar_stop_and_target_resolves_to_stop():
    outcome = simulate_candidate(
        candidate(),
        [Bar(100, 103, 97, 101)],
        maker_fee=0, taker_fee=0, spread_rate=0, slippage_rate=0,
    )
    assert outcome["exit_reason"] == "STOP"
    assert outcome["gross_r"] == -1.0
    assert outcome["net_r"] == -1.0


def test_market_fill_uses_next_open_and_shifts_plan_geometry():
    outcome = simulate_candidate(
        candidate(),
        [Bar(101, 101.5, 100.5, 101.2), Bar(101.2, 104, 101, 103)],
        maker_fee=0, taker_fee=0, spread_rate=0, slippage_rate=0,
    )
    assert outcome["entry"] == 101.0
    assert outcome["stop_loss"] == 99.0
    assert outcome["gross_r"] > 0


def test_limit_order_is_not_filled_without_price_touch():
    outcome = simulate_candidate(
        candidate(entry_type="LIMIT"),
        [Bar(101, 103, 100.5, 102)],
        maker_fee=0, taker_fee=0, spread_rate=0, slippage_rate=0,
    )
    assert outcome is None


def test_costs_reduce_gross_expectancy():
    outcome = simulate_candidate(
        candidate(),
        [Bar(100, 103, 99.5, 102.5)],
        maker_fee=0.0002, taker_fee=0.00055,
        spread_rate=0.0002, slippage_rate=0.0003,
    )
    assert outcome is not None
    assert outcome["cost_r"] > 0
    assert outcome["net_r"] < outcome["gross_r"]


def test_short_targets_are_directionally_simulated():
    outcome = simulate_candidate(
        candidate("SHORT"),
        [Bar(100, 100.5, 97, 98)],
        maker_fee=0, taker_fee=0, spread_rate=0, slippage_rate=0,
    )
    assert outcome is not None
    assert outcome["gross_r"] > 0

from strategy_backtest import _walk_forward_summary


def test_funding_cost_is_applied_at_historical_settlement():
    bar = Bar(100, 103, 99.5, 102.5, time=1_700_000_000_000)
    funding = [{"timestamp": 1_700_000_450_000, "value": 0.001}]
    long_result = simulate_candidate(
        candidate("LONG"), [bar],
        maker_fee=0, taker_fee=0, spread_rate=0, slippage_rate=0,
        funding_events=funding,
    )
    short_result = simulate_candidate(
        candidate("SHORT"), [Bar(100, 100.5, 97, 98, time=1_700_000_000_000)],
        maker_fee=0, taker_fee=0, spread_rate=0, slippage_rate=0,
        funding_events=funding,
    )
    assert long_result["funding_pnl_r"] < 0
    assert short_result["funding_pnl_r"] == 0
    short_pays = simulate_candidate(
        candidate("SHORT"), [Bar(100, 100.5, 97, 98, time=1_700_000_000_000)],
        maker_fee=0, taker_fee=0, spread_rate=0, slippage_rate=0,
        funding_events=[{"timestamp": 1_700_000_450_000, "value": -0.001}],
    )
    assert short_pays["funding_pnl_r"] < 0
    assert long_result["net_r"] < long_result["gross_r"]
    assert short_pays["net_r"] < short_pays["gross_r"]


def test_walk_forward_uses_expanding_train_and_sequential_test_windows():
    start = 1_700_000_000_000
    end = start + 600_000
    rows = [
        {"closed_at_ms": start + 50_000, "net_r": 1.0, "cost_r": 0.1},
        {"closed_at_ms": start + 250_000, "net_r": -1.0, "cost_r": 0.1},
        {"closed_at_ms": start + 450_000, "net_r": 2.0, "cost_r": 0.1},
    ]
    folds = _walk_forward_summary(rows, start, end, folds=2)
    assert len(folds) == 2
    assert folds[0]["train_end_ms"] == folds[0]["test_start_ms"]
    assert folds[1]["train_start_ms"] == start
    assert folds[1]["train"]["trades"] >= folds[0]["train"]["trades"]
    assert folds[0]["test_end_ms"] == folds[1]["test_start_ms"]


def test_limit_gap_through_fills_at_open_as_marketable_limit():
    outcome = simulate_candidate(
        candidate(entry_type="LIMIT"),
        [Bar(99.0, 103.0, 98.5, 102.0)],
        maker_fee=0.0002, taker_fee=0.00055, spread_rate=0.0002, slippage_rate=0.0003,
    )
    assert outcome is not None
    assert outcome["entry"] == 99.0
    assert outcome["entry_type"] == "MARKETABLE_LIMIT"
    assert outcome["exit_reason"] == "TRAILING_STOP"


def test_intrabar_limit_fill_excludes_fill_candle_targets():
    outcome = simulate_candidate(
        candidate(entry_type="LIMIT"),
        [
            Bar(101.0, 102.0, 99.5, 101.5),
            Bar(101.5, 103.0, 100.5, 102.8),
            Bar(102.8, 103.0, 99.5, 100.0),
        ],
        maker_fee=0, taker_fee=0, spread_rate=0, slippage_rate=0,
    )
    assert outcome is not None
    assert outcome["entry"] == 100.0
    assert outcome["entry_type"] == "LIMIT"
    assert outcome["bars_held"] == 3
    assert outcome["exit_reason"] == "TRAILING_STOP"


def test_shared_max_holding_horizon_closes_unresolved_position_at_last_close():
    bars = [Bar(100.0, 101.0, 99.0, 101.0, time=1_700_000_000_000 + i * 900_000) for i in range(32)]
    outcome = simulate_candidate(
        candidate(), bars, maker_fee=0, taker_fee=0, spread_rate=0, slippage_rate=0, max_bars=32
    )
    assert outcome is not None
    assert outcome["exit_reason"] == "TIME_EXIT"
    assert outcome["bars_held"] == 32
    assert outcome["gross_r"] == 0.5


def test_strategy_snapshot_uses_decision_close_not_next_bar_open():
    bars = [
        Bar(99.0, 101.0, 98.0, 100.0, time=1_700_000_000_000),
        Bar(500.0, 510.0, 490.0, 505.0, time=1_700_000_900_000),
    ]
    history = {"symbol": "BTC/USDT:USDT", "15m": bars}
    snapshot = _snapshot_at(history, 0)
    assert snapshot["current_price"] == 100.0
    assert snapshot["current_price_source"] == "BACKTEST_DECISION_15M_CLOSE"
    assert snapshot["current_price_timestamp_ms"] == bars[0].time + 900_000


def test_smc_and_strategy_replays_share_marketable_limit_fill_cost_and_funding():
    bar_time = 1_700_000_000_000
    bars = [
        Bar(99.0, 99.5, 98.5, 99.2, time=bar_time),
        Bar(99.2, 103.0, 98.5, 102.0, time=bar_time + 900_000),
    ]
    funding = [{"timestamp": bar_time + 1_800_000, "value": 0.001}]
    fees = {
        "maker_fee": 0.0002, "taker_fee": 0.00055,
        "spread_rate": 0.0002, "slippage_rate": 0.0003,
    }
    strategy = simulate_candidate(
        candidate(entry_type="LIMIT"), bars, funding_events=funding, **fees
    )
    runner = BacktestRunner(
        maker_fee_rate=fees["maker_fee"], taker_fee_rate=fees["taker_fee"],
        spread_rate=fees["spread_rate"], slippage_rate=fees["slippage_rate"],
        tp_weights=_configured_partial_tp_weights(),
    )
    smc = runner._to_trade(
        {
            "decision": {"action": "EXECUTE"},
            "signal": {"signal": "LONG"},
            "risk": {"entry": 100.0, "stop_loss": 98.0, "tp1": 102.5, "tp2": 104.0, "tp3": 106.0},
            "analysis": {"entry": {"entry_type": "LIMIT"}},
        },
        bars, entry_index=0, funding_records=funding,
    )
    assert strategy is not None and smc is not None
    assert strategy["entry"] == smc["entry"] == 99.0
    assert strategy["entry_type"] == smc["entry_type"] == "MARKETABLE_LIMIT"
    assert strategy["gross_r"] == smc["gross_rr"]
    assert abs(strategy["trading_cost_r"] - smc["execution_cost_rr"]) < 1e-4
    assert strategy["funding_cost_r"] == smc["funding_cost_r"]
    assert abs(strategy["net_r"] - smc["net_rr"]) < 1e-4


def test_smc_and_strategy_replays_share_bounded_market_fallback():
    bar_time = 1_700_100_000_000
    bars = [
        Bar(100.1, 100.5, 100.2, 100.3, time=bar_time),
        Bar(100.3, 106.5, 100.2, 105.0, time=bar_time + 900_000),
        Bar(105.0, 105.5, 99.9, 101.0, time=bar_time + 1_800_000),
    ]
    plan = candidate(entry_type="LIMIT")
    plan.update({"tp1": 106.0, "tp2": 108.0, "tp3": 110.0, "atr": 1.0})
    strategy = simulate_candidate(
        plan, bars, maker_fee=0, taker_fee=0, spread_rate=0, slippage_rate=0, max_bars=3
    )
    runner = BacktestRunner(
        maker_fee_rate=0, taker_fee_rate=0, spread_rate=0, slippage_rate=0,
        tp_weights=_configured_partial_tp_weights(),
    )
    smc = runner._to_trade(
        {
            "decision": {"action": "EXECUTE"},
            "signal": {"signal": "LONG"},
            "risk": {"entry": 100.0, "stop_loss": 98.0, "tp1": 106.0, "tp2": 108.0, "tp3": 110.0, "atr": 1.0},
            "analysis": {"entry": {"entry_type": "LIMIT"}},
        },
        bars, entry_index=0,
    )
    assert strategy is not None and smc is not None
    assert strategy["entry_type"] == smc["entry_type"] == "MARKET_FALLBACK"
    assert strategy["entry"] == smc["entry"] == 100.1
    assert strategy["gross_r"] == smc["gross_rr"]
    assert abs(strategy["net_r"] - smc["net_rr"]) < 1e-4


def test_pending_limit_fill_after_multiple_bars_matches_smc_expiry_and_time_exit():
    bars = [
        Bar(100.0, 101.0, 99.0, 100.0, time=1_700_199_100_000),
        Bar(105.0, 106.0, 104.0, 105.0, time=1_700_200_000_000),
        Bar(101.0, 102.0, 99.5, 101.0, time=1_700_200_900_000),
        Bar(101.0, 103.0, 100.5, 102.8, time=1_700_201_800_000),
    ]
    plan = candidate(entry_type="LIMIT")
    plan.update({"tp1": 110.0, "tp2": 112.0, "tp3": 115.0})
    strategy = simulate_candidate(
        plan, bars[1:], maker_fee=0.0002, taker_fee=0.00055,
        spread_rate=0.0002, slippage_rate=0.0003,
        max_bars=2, limit_expiry_bars=2,
    )
    runner = BacktestRunner(
        maker_fee_rate=0.0002, taker_fee_rate=0.00055,
        spread_rate=0.0002, slippage_rate=0.0003,
        tp_weights=_configured_partial_tp_weights(),
        limit_expiry_bars=2, max_holding_bars=2,
    )
    smc = runner._to_trade(
        {
            "decision": {"action": "EXECUTE"},
            "signal": {"signal": "LONG"},
            "risk": {"entry": 100.0, "stop_loss": 98.0, "tp1": 110.0, "tp2": 112.0, "tp3": 115.0},
            "analysis": {"entry": {"entry_type": "LIMIT"}},
        },
        bars, entry_index=1,
    )
    assert strategy is not None and smc is not None
    assert strategy["fill_offset"] == 1
    assert strategy["fill_time_ms"] == bars[2].time
    assert strategy["entry_type"] == smc["entry_type"] == "LIMIT"
    assert strategy["entry"] == smc["entry"] == 100.0
    assert strategy["gross_r"] == smc["gross_rr"]
    assert abs(strategy["net_r"] - smc["net_rr"]) < 1e-4


def test_pre_fill_target_touches_rebase_targets_identically():
    bars = [
        Bar(100.0, 103.0, 99.0, 102.0, time=1_700_300_000_000),
        Bar(105.0, 105.5, 104.5, 105.0, time=1_700_300_900_000),
        Bar(101.0, 102.0, 99.5, 101.0, time=1_700_301_800_000),
        Bar(101.0, 107.0, 100.5, 106.5, time=1_700_302_700_000),
    ]
    plan = candidate(entry_type="LIMIT")
    strategy = simulate_candidate(
        plan, bars[1:], maker_fee=0, taker_fee=0, spread_rate=0, slippage_rate=0,
        max_bars=2, limit_expiry_bars=3, signal_candle=bars[0],
    )
    runner = BacktestRunner(
        maker_fee_rate=0, taker_fee_rate=0, spread_rate=0, slippage_rate=0,
        tp_weights=_configured_partial_tp_weights(),
        limit_expiry_bars=3, max_holding_bars=2,
    )
    smc = runner._to_trade(
        {
            "decision": {"action": "EXECUTE"},
            "signal": {"signal": "LONG"},
            "risk": {"entry": 100.0, "stop_loss": 98.0, "tp1": 102.5, "tp2": 104.0, "tp3": 106.0},
            "analysis": {"entry": {"entry_type": "LIMIT"}},
        },
        bars, entry_index=1,
    )
    assert strategy is not None and smc is not None
    assert strategy["target_rebased_after_pre_fill_touch"] is True
    assert strategy["entry_type"] == smc["entry_type"] == "LIMIT"
    assert strategy["gross_r"] == smc["gross_rr"] == 3.0
    assert abs(strategy["net_r"] - smc["net_rr"]) < 1e-4
