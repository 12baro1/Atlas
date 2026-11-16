"""Segmentation and JSON/CSV report export tests."""
import csv
import json
from types import SimpleNamespace

from backtest_runner import BacktestRunner
from segmentation_report import (
    build_report_payload, classify_tp_behavior, flatten_report_rows,
    segment_breakdown, trade_dimensions, trade_metrics, volatility_label,
    write_csv_report, write_json_report,
)
from trade_journal import TradeJournal


def _trade(**overrides):
    trade = {
        "direction": "LONG", "entry_type": "LIMIT", "regime": "TRENDING_UP",
        "volatility_ratio": 1.0, "poi_source": "FVG", "market_phase": "Expansion",
        "result": "WIN", "net_rr": 2.0, "gross_rr": 2.2,
        "execution_cost_rr": 0.2, "_levels": [1, 2], "exit_reason": "TP2",
    }
    trade.update(overrides)
    return trade


def test_dimensions_map_backtest_fields_and_derive_volatility():
    dimensions = trade_dimensions(_trade())
    assert dimensions == {
        "entry_type": "LIMIT", "regime": "TRENDING_UP", "volatility": "NORMAL",
        "poi_source": "FVG", "market_phase": "EXPANSION",
        "tp_behavior": "TP2_HIT", "direction": "LONG",
    }
    assert volatility_label(0.50) == "COMPRESSION"
    assert volatility_label(1.80) == "EXPANSION"
    assert volatility_label(None) == "UNKNOWN"


def test_tp_behavior_distinguishes_partial_stop_from_clean_stop():
    assert classify_tp_behavior(_trade(result="WIN", _levels=[1])) == "TP1_HIT"
    assert classify_tp_behavior(_trade(result="LOSS", _levels=[1])) == "TP1_THEN_STOP"
    assert classify_tp_behavior(_trade(result="LOSS", _levels=[])) == "FULL_STOP"
    assert classify_tp_behavior({"result": "LOSS", "close_reason": "stop_loss_hit"}) == "FULL_STOP"
    assert classify_tp_behavior({"result": "WIN", "close_reason": "target_hit"}) == "TP1_HIT"


def test_segment_breakdown_pools_entry_type_and_regime_metrics():
    trades = [
        _trade(net_rr=2.0, gross_rr=2.2, _levels=[1, 2]),
        _trade(net_rr=-1.0, gross_rr=-1.0, result="LOSS", _levels=[], exit_reason="STOP"),
        _trade(direction="SHORT", entry_type="MARKET", regime="RANGING",
               volatility_ratio=1.8, poi_source="ORDER_BLOCK", market_phase="Ranging",
               net_rr=-1.1, gross_rr=-1.0, result="LOSS", _levels=[]),
    ]
    segments = segment_breakdown(trades)
    assert segments["entry_type"]["LIMIT"]["total"] == 2
    assert segments["entry_type"]["LIMIT"]["expectancy"] == 0.5
    assert segments["entry_type"]["MARKET"]["total"] == 1
    assert segments["regime"]["TRENDING_UP"]["net_rr"] == 1.0
    assert segments["volatility"]["EXPANSION"]["total"] == 1
    assert segments["poi_source"]["ORDER_BLOCK"]["total"] == 1


def test_live_journal_metrics_do_not_relabel_net_rr_as_gross():
    metrics = trade_metrics([{"result": "WIN", "pnl_rr": 1.5}])
    assert metrics["net_rr"] == 1.5
    assert metrics["gross_rr"] is None
    assert metrics["gross_expectancy"] is None
    assert metrics["gross_profit_factor"] is None


def test_json_and_csv_exports_are_atomic_and_keep_sample_size_visible(tmp_path):
    trades = [_trade(), _trade(result="LOSS", net_rr=-1.0, gross_rr=-1.0, _levels=[])]
    payload = build_report_payload(
        {"BTC/USDT:USDT": {"trades": trades}}, {"trades": trades},
        source="test", metadata={"days": 30},
    )
    json_path, csv_path = tmp_path / "report.json", tmp_path / "report.csv"
    write_json_report(json_path, payload)
    write_csv_report(csv_path, flatten_report_rows(payload))
    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    assert loaded["schema_version"] == 1
    assert loaded["sample_base"] == "realized_closed_trades"
    assert loaded["symbols"]["BTC/USDT:USDT"]["summary"]["total"] == 2
    assert loaded["combined"]["segments"]["tp_behavior"]["TP2_HIT"]["total"] == 1
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows and rows[0]["symbol"] == "BTC/USDT:USDT"
    assert rows[0]["dimension"] == "summary" and rows[0]["total"] == "2"
    assert rows[0]["low_sample"] == "True"
    assert any(row["dimension"] == "tp_behavior" and row["segment"] == "TP2_HIT" for row in rows)


def test_backtest_trade_carries_regime_poi_and_tp_segments():
    def candle(time, open_, high, low, close):
        return SimpleNamespace(time=time, open=open_, high=high, low=low, close=close)
    runner = BacktestRunner(partial_exits=False)
    candles = [candle(1, 97.0, 99.0, 94.0, 96.0), candle(2, 96.0, 101.5, 95.5, 101.0)]
    result = {
        "decision": {"action": "EXECUTE"}, "signal": {"signal": "LONG"},
        "risk": {"entry": 95.0, "stop_loss": 90.0, "tp1": 100.0, "tp2": 105.0, "tp3": 110.0},
        "analysis": {
            "entry": {"entry_type": "LIMIT", "poi_source": "FVG"},
            "market_regime": {"regime": "TRENDING_UP", "directional_bias": "BULLISH", "volatility_ratio": 1.1},
            "market_phase": {"phase": "Expansion"},
        },
    }
    trade = runner._to_trade(result, candles, entry_index=0)
    assert trade is not None
    assert trade["poi_source"] == "FVG"
    assert trade["regime"] == "TRENDING_UP"
    assert trade["volatility_regime"] == "NORMAL"
    assert trade["market_phase"] == "Expansion"
    assert trade["tp_behavior"] == "TP1_HIT"
    runner._record(trade)
    stats = runner.statistics()
    assert stats["segment_breakdown"]["entry_type"]["LIMIT"]["total"] == 1
    assert stats["segment_breakdown"]["regime"]["TRENDING_UP"]["total"] == 1
    assert stats["segment_breakdown"]["poi_source"]["FVG"]["total"] == 1
    assert stats["segment_breakdown"]["tp_behavior"]["TP1_HIT"]["total"] == 1


def test_trade_journal_persists_segment_fields():
    journal = TradeJournal()
    record = journal.register_trade(
        {"side": "LONG", "entry": 100.0, "stop_loss": 99.0, "tp1": 101.0, "entry_type": "LIMIT"},
        analysis={"analysis": {
            "entry": {"entry_type": "LIMIT", "poi_source": "FVG"},
            "market_regime": {"regime": "TRENDING_UP", "volatility_ratio": 1.2},
        }},
        symbol="BTC/USDT:USDT",
    )
    assert record["entry_type"] == "LIMIT"
    assert record["poi_source"] == "FVG"
    assert record["regime"] == "TRENDING_UP"
    assert record["volatility_ratio"] == 1.2
