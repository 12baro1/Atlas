from strategy_backtest import simulate_candidate


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
    assert outcome["exit_reason"] == "STOP_AND_TARGET_SAME_BAR_STOP_FIRST"
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
