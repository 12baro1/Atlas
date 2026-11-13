import pytest

from execution_costs import estimate_plan_cost, estimate_stop_cost, realized_trade_cost
from config import Config
from position_manager import PositionManager


def test_limit_entry_and_target_exit_use_maker_fees_only():
    cost = estimate_plan_cost(
        entry_price=100.0,
        targets={"tp1": 102.0},
        weights={"tp1": 1.0},
        entry_type="LIMIT",
        maker_fee_rate=0.0002,
        taker_fee_rate=0.00055,
        spread_rate=0.0002,
        slippage_rate=0.0003,
    )
    assert cost["entry_fee"] == pytest.approx(0.02)
    assert cost["exit_fee"] == pytest.approx(0.0204)
    assert cost["spread"] == 0
    assert cost["slippage"] == 0
    assert cost["total"] == pytest.approx(0.0404)


def test_market_entry_charges_taker_and_one_way_market_friction():
    cost = estimate_plan_cost(
        entry_price=100.0,
        targets={"tp1": 102.0},
        weights={"tp1": 1.0},
        entry_type="MARKET",
        maker_fee_rate=0.0002,
        taker_fee_rate=0.00055,
        spread_rate=0.0002,
        slippage_rate=0.0003,
    )
    assert cost["entry_fee"] == pytest.approx(0.055)
    assert cost["spread"] == pytest.approx(0.02)
    assert cost["slippage"] == pytest.approx(0.03)
    assert cost["total"] == pytest.approx(0.1254)


def test_stop_cost_uses_taker_exit_and_market_friction():
    cost = estimate_stop_cost(
        entry_price=100.0,
        stop_price=99.0,
        entry_type="LIMIT",
        maker_fee_rate=0.0002,
        taker_fee_rate=0.00055,
        spread_rate=0.0002,
        slippage_rate=0.0003,
    )
    assert cost["entry_fee"] == pytest.approx(0.02)
    assert cost["exit_fee"] == pytest.approx(99.0 * 0.00055)
    assert cost["spread"] == pytest.approx(99.0 * 0.0002)
    assert cost["slippage"] == pytest.approx(99.0 * 0.0003)


def test_partial_tp_then_trailing_stop_charges_each_exit_type_once():
    cost = realized_trade_cost(
        entry_price=100.0,
        exit_price=100.0,
        entry_type="LIMIT",
        exit_reason="TRAILING_STOP",
        targets=[102.0, 104.0, 106.0],
        reached_levels=[1],
        tp_weights={"tp1": 0.5, "tp2": 0.3, "tp3": 0.2},
        partial_exits=True,
        maker_fee_rate=0.0002,
        taker_fee_rate=0.00055,
        spread_rate=0.0002,
        slippage_rate=0.0003,
    )
    expected = (
        100.0 * 0.0002
        + 102.0 * 0.5 * 0.0002
        + 100.0 * 0.5 * 0.00055
        + 100.0 * 0.5 * 0.0002
        + 100.0 * 0.5 * 0.0003
    )
    assert cost["total"] == pytest.approx(expected)


def test_position_manager_breakeven_stop_uses_per_leg_costs():
    manager = PositionManager()
    position = manager.open("BTC/USDT:USDT", {
        "side": "LONG",
        "entry": 100.0,
        "entry_type": "LIMIT",
        "stop_loss": 99.0,
        "tp1": 101.0,
        "tp2": 102.0,
        "tp3": 103.0,
    })
    manager.update("BTC/USDT:USDT", 101.0)
    expected = estimate_stop_cost(
        entry_price=100.0,
        stop_price=100.0,
        entry_type="LIMIT",
        maker_fee_rate=Config.MAKER_FEE_RATE,
        taker_fee_rate=Config.TAKER_FEE_RATE,
        spread_rate=Config.STOP_SPREAD_BUFFER_RATE,
        slippage_rate=Config.STOP_SLIPPAGE_BUFFER_RATE,
    )["total"]
    assert position["stop_loss"] == pytest.approx(100.0 + expected)



def test_marketable_limit_gap_fill_uses_taker_costs():
    cost = estimate_plan_cost(
        entry_price=100.0,
        targets={"tp1": 102.0},
        weights={"tp1": 1.0},
        entry_type="MARKETABLE_LIMIT",
        maker_fee_rate=0.0002,
        taker_fee_rate=0.00055,
        spread_rate=0.0002,
        slippage_rate=0.0003,
    )
    assert cost["entry_fee"] == pytest.approx(0.055)
    assert cost["spread"] == pytest.approx(0.02)
    assert cost["slippage"] == pytest.approx(0.03)
