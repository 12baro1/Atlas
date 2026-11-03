import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest_engine import BacktestEngine
from decision_engine import DecisionEngine
from orderbook_engine import OrderBookEngine


def test_decision_uses_cost_adjusted_rr_instead_of_max_tp_rr():
    engine = DecisionEngine()
    risk = {
        "selected_rr": 4.5,
        "rr": 4.5,
        "weighted_rr": 2.0,
        "weighted_net_rr": 1.2,
        "execution_rr": 1.2,
    }
    assert engine._resolve_rr_value(risk) == 4.5
    assert engine._resolve_execution_rr_value(risk) == 1.2
    blockers, valid = engine._collect_risk_blockers(
        risk={"risk": 1.0, "stop_loss": 99.0, "weighted_rr": 2.0,
              "weighted_net_rr": 1.2},
        rr_value=1.2,
        minimum_rr=1.5,
        position_size=1.0,
    )
    assert not valid
    assert any("RR below minimum" in item for item in blockers)


def test_orderflow_opposition_blocks_market_entry_even_if_book_is_neutral():
    engine = OrderBookEngine()
    now = 100_000
    trades = [
        {"timestamp": now - 1000, "price": 100.0, "amount": 5.0, "side": "sell"},
        {"timestamp": now - 900, "price": 100.0, "amount": 1.0, "side": "buy"},
    ]
    snapshot = {
        "timestamp": now,
        "bids": [[99.99, 10.0]],
        "asks": [[100.01, 10.0]],
    }
    result = engine.analyze(snapshot, direction="LONG", now_ms=now, trades=trades)
    assert result["trade_flow_active"] is True
    assert result["trade_flow_opposing"] is True
    assert result["opposing"] is True
    assert result["market_entry_allowed"] is False


def test_orderflow_can_be_used_when_orderbook_snapshot_is_missing():
    engine = OrderBookEngine()
    now = 100_000
    trades = [
        {"timestamp": now - 1000, "price": 100.0, "amount": 4.0, "side": "buy"},
        {"timestamp": now - 900, "price": 100.0, "amount": 1.0, "side": "sell"},
    ]
    result = engine.analyze(None, direction="LONG", now_ms=now, trades=trades)
    assert result["active"] is False
    assert result["trade_flow_active"] is True
    assert result["trade_flow_supportive"] is True


def test_partial_exit_backtest_accounts_for_tp1_then_stop():
    result = BacktestEngine.simulate_trade(
        entry=100.0,
        stop_loss=99.0,
        targets=[102.0, 104.0, 106.0],
        side="LONG",
        partial_weights=[0.4, 0.3, 0.3],
        round_trip_cost_rate=0.0,
        candles=[
            {"high": 102.1, "low": 100.5},
            {"high": 101.0, "low": 98.9},
        ],
    )
    assert result["result"] == "WIN"
    assert result["targets_hit"] == 1
    assert result["close_reason"] == "stop_after_partial_tp"
    assert result["gross_rr"] == 0.2


def test_backtest_records_realized_net_r_from_partial_simulation():
    outcome = BacktestEngine.simulate_trade(
        entry=100.0,
        stop_loss=99.0,
        targets=[102.0, 104.0, 106.0],
        side="LONG",
        partial_weights=[0.4, 0.3, 0.3],
        round_trip_cost_rate=0.0,
        candles=[
            {"high": 102.1, "low": 100.5},
            {"high": 101.0, "low": 98.9},
        ],
    )
    engine = BacktestEngine()
    engine.record(outcome)
    assert engine.statistics()["expectancy"] == 0.2


def test_ambiguous_same_candle_stop_and_target_is_resolved_stop_first():
    result = BacktestEngine.simulate_trade(
        entry=100.0,
        stop_loss=99.0,
        targets=[102.0],
        side="LONG",
        round_trip_cost_rate=0.0,
        candles=[{"high": 102.5, "low": 98.5}],
    )
    assert result["result"] == "LOSS"
    assert result["gross_rr"] == -1.0
    assert result["targets_hit"] == 0


def test_performance_gate_requires_sample_size_and_positive_metrics():
    engine = BacktestEngine()
    for index in range(200):
        engine.record({
            "result": "WIN" if index % 4 else "LOSS",
            "rr": 2.0 if index % 4 else 1.0,
            "side": "LONG" if index % 2 else "SHORT",
        })
    gate = engine.performance_gate(minimum_trades=200, minimum_profit_factor=1.5,
                                   maximum_drawdown_pct=10.0, risk_percent=1.0)
    assert gate["sample_sufficient"] is True
    assert gate["ready"] is True
    assert set(engine.trade_analytics()["direction_breakdown"]) == {"LONG", "SHORT"}


def test_performance_gate_does_not_pass_small_sample():
    engine = BacktestEngine()
    for _ in range(20):
        engine.record({"result": "WIN", "rr": 5.0, "side": "LONG"})
    gate = engine.performance_gate()
    assert gate["ready"] is False
    assert gate["sample_sufficient"] is False
