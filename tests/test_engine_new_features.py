"""Full-pipeline integration test: engine.analyze() produces the new
structure features (EQH/EQL, IFVG, trendlines, internal/external structure)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.candle import Candle
from engine import AtlasEngine


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
        # engine.analyze, top-level "15m" anahtarından candles okur
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
    eng = AtlasEngine()
    return eng


@pytest.fixture(autouse=True)
def isolate_caching(monkeypatch):
    import config as config_module
    monkeypatch.setattr(config_module.Config, "STATE_ENGINE_ENABLED", False, raising=False)
    monkeypatch.setattr(config_module.Config, "INCREMENTAL_ANALYSIS_ENABLED", False, raising=False)


def test_analyze_produces_structure_state(engine):
    result = engine.analyze(synthetic_data())
    analysis = result["analysis"]

    assert "structure" in analysis
    assert "ifvg" in analysis
    assert "trendlines" in analysis
    assert "trendline_sweep" in analysis
    assert "internal_structure" in analysis
    assert "external_structure" in analysis
    assert "eqh_eql" in analysis


def test_analyze_scanner_statistics_backtest_recording(engine):
    result = engine.analyze(synthetic_data())
    assert engine.scanner.summary()["total"] == 1
    assert engine.statistics.summary()["total_signals"] >= 0
    assert engine.backtest.statistics()["total"] >= 0


def test_analyze_twice_accumulates(engine):
    engine.analyze(synthetic_data())
    engine.analyze(synthetic_data())
    assert engine.scanner.summary()["total"] == 2


def test_eqh_eql_clustering():
    engine = AtlasEngine()
    liquidity = [
        {"type": "BUY_SIDE", "price": 100.0, "touches": 2, "index": 10},
        {"type": "BUY_SIDE", "price": 100.05, "touches": 2, "index": 20},
        {"type": "SELL_SIDE", "price": 95.0, "touches": 1, "index": 5},
    ]
    result = engine._detect_eqh_eql(liquidity)

    assert result["active"] is True
    assert len(result["eqh"]) == 1
    assert result["eqh"][0]["level"] == "EQH"
    assert result["eqh"][0]["touches"] == 4
    assert result["eql"] == []


def test_internal_external_structure():
    engine = AtlasEngine()
    structure = [
        {"index": 1, "price": 10, "kind": "LOW", "label": "L?", "bos": False, "choch": False},
        {"index": 2, "price": 20, "kind": "HIGH", "label": "H?", "bos": True, "choch": False},
        {"index": 3, "price": 15, "kind": "LOW", "label": "HL", "bos": False, "choch": False},
        {"index": 4, "price": 25, "kind": "HIGH", "label": "HH", "bos": False, "choch": False},
    ]
    internal, external = engine._detect_internal_external_structure(structure, [], {})

    # BOS noktası (index 2) dış yapıda; diğerleri iç yapıda
    assert len(external) >= 1
    assert external[0]["index"] == 2
    assert all(item["index"] != 2 for item in internal)