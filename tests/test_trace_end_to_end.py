"""Uçtan uca trace testleri: veriden karara aynı trace_id; gözlemsel kalır."""
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.candle import Candle
from engine import AtlasEngine
from strategy_lab import SevenStrategyLab
from trace_context import new_trace_id


def make_candle(i, base, amp=1.0):
    open_ = base + amp * (0.5 if i % 2 else -0.2)
    close = base + amp * (-0.3 if i % 2 else 0.4)
    high = max(open_, close) + amp * 0.6
    low = min(open_, close) - amp * 0.5
    return Candle(i, open_, high, low, close, 100)


def synthetic_data(symbol="BTC/USDT:USDT"):
    candles = [make_candle(i, 100 + i * 0.1) for i in range(300)]
    return {
        "symbol": symbol,
        "15m": candles,
        "1w": candles,
        "1d": candles,
        "4h": candles,
        "1h": candles,
        "timeframes": {
            "15m": {"candles": candles},
            "1h": {"candles": candles},
            "4h": {"candles": candles},
            "1d": {"candles": candles},
            "1w": {"candles": candles},
        },
        "economic_events": [],
    }


@pytest.fixture
def engine():
    return AtlasEngine()


@pytest.fixture(autouse=True)
def isolate_caching(monkeypatch):
    import config as config_module
    monkeypatch.setattr(config_module.Config, "STATE_ENGINE_ENABLED", False, raising=False)
    monkeypatch.setattr(config_module.Config, "INCREMENTAL_ANALYSIS_ENABLED", False, raising=False)


PIPELINE_STAGES = {
    "SHARED_MARKET_EVIDENCE", "STRATEGY_SETUP",
    "SPECIALIST_MOTORS", "FINAL_DECISION", "SIGNAL_OUTPUT",
}


def test_engine_analysis_carries_one_trace_id_across_all_stages(engine):
    result = engine.analyze(synthetic_data())
    trace = result["trace"]

    assert result["trace_id"].startswith("trace-")
    assert trace["trace_id"] == result["trace_id"]
    stage_names = {entry["stage"] for entry in trace["stages"]}
    assert PIPELINE_STAGES <= stage_names
    # Aynı analizdeki her aşama aynı trace_id'yi taşır.
    assert {entry["trace_id"] for entry in trace["stages"]} == {result["trace_id"]}
    # Strateji üretimi ve ortak filtre adayı başına kaydedilir.
    strategy_stage_symbols = {
        entry["strategy"] for entry in trace["stages"] if entry["stage"] == "STRATEGY_SETUP"
    }
    assert len(strategy_stage_symbols) == 7


def test_each_fresh_analysis_gets_a_new_trace_id(engine):
    first = engine.analyze(synthetic_data())
    second = engine.analyze(synthetic_data())

    assert first["trace_id"] != second["trace_id"]


def test_trace_id_from_data_engine_is_kept_not_regenerated(engine):
    data = synthetic_data()
    preset = new_trace_id(now_ms=1_700_000_000_000)
    data["trace_id"] = preset

    result = engine.analyze(data)

    assert result["trace_id"] == preset
    assert all(entry["trace_id"] == preset for entry in result["trace"]["stages"])


def test_strategy_report_exposes_trace_id_and_seven_data_usage_rows(engine):
    result = engine.analyze(synthetic_data())
    report = result["strategy_lab"]

    assert report["trace_id"] == result["trace_id"]
    rows = report["data_usage"]
    assert len(rows) == 7
    for row in rows:
        assert row["status"] in {
            "SELECTED", "FILTERED_NOT_SELECTED", "BLOCKED_COMMON_FILTER", "RAW_SETUP",
            "FILTERED_SETUP", "MISSING_DATA", "INSUFFICIENT_HISTORY",
            "CONDITION_NOT_MET", "NO_SETUP", "ERROR",
        }
        assert isinstance(row["setup_produced"], bool)
        assert row["common_filter_result"] in {"PASSED", "REJECTED", "NOT_REACHED"}
        # Kullanılmayan veri türleri kullanılmadı olarak işaretlenir.
        for feed_name, feed in row["feeds"].items():
            if not feed["used"]:
                assert feed["status"] == "NOT_USED"
    by_id = {row["strategy_id"]: row for row in rows}
    # Trend stratejisi yalnızca mum okur; mikroyapı beslemesi kullanılmadı.
    assert by_id["trend_pullback"]["feeds"]["orderbook"]["used"] is False
    assert by_id["trend_pullback"]["feeds"]["orderbook"]["status"] == "NOT_USED"
    # Orderflow orderbook + recent trades + CVD + footprint okur.
    for feed in ("orderbook", "recent_trades", "trade_flow_history", "footprint"):
        assert by_id["orderflow_momentum"]["feeds"][feed]["used"] is True


def test_trace_is_observability_only_and_never_changes_strategy_output():
    base = synthetic_data()
    with_trace = copy.deepcopy(base)
    with_trace["trace_id"] = "trace-poison-0000"
    with_trace["trace"] = {
        "trace_id": "trace-poison-0000",
        "stages": [{"stage": "FINAL_DECISION", "detail": {"force": "SHORT"}}],
    }

    clean_report = SevenStrategyLab().analyze(copy.deepcopy(base))
    traced_report = SevenStrategyLab().analyze(with_trace)

    # Trace verisi karar mantığına giremez: sonuçlar birebir aynı kalır.
    assert traced_report["selected"] == clean_report["selected"]
    assert traced_report["diagnostics"]["status_counts"] == clean_report["diagnostics"]["status_counts"]
    assert traced_report["trace_id"] == "trace-poison-0000"


def test_strategy_generator_modules_never_read_trace_data():
    """Strateji üreticileri trace'i okumaz; yalnızca strategy_lab kayıt yapar."""
    import pathlib

    root = pathlib.Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    offenders = []
    for path in root.glob("strategies/**/*.py"):
        text = path.read_text(encoding="utf-8")
        if 'data.get("trace")' in text or 'data.get("trace_id")' in text:
            offenders.append(str(path))
    assert offenders == []
