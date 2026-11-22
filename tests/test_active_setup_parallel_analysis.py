"""Aktif setup, yeni analizi engellemez: 7 strateji yeniden çalışır, aktif
setup ayrı tutulur, üzerine asla yazılmaz."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.candle import Candle
from engine import AtlasEngine
from state_engine import StateEngine


def make_candle(i, base, amp=1.0):
    open_ = base + amp * (0.5 if i % 2 else -0.2)
    close = base + amp * (-0.3 if i % 2 else 0.4)
    high = max(open_, close) + amp * 0.6
    low = min(open_, close) - amp * 0.5
    return Candle(i, open_, high, low, close, 100)


def synthetic_data(symbol="BTC/USDT:USDT", current_price=100.0):
    candles = [make_candle(i, 100 + i * 0.1) for i in range(300)]
    return {
        "symbol": symbol,
        "current_price": current_price,
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


def selected_trend_candidate():
    """Deterministik, ortak filtreyi geçebilen bir trend_pullback adayı."""
    return {
        "direction": "LONG", "entry_type": "MARKET", "entry": 100.0,
        "stop_loss": 98.0, "tp1": 102.5, "tp2": 104.0, "tp3": 106.0,
        "strength": 85.0, "reasons": ["deterministic-test-candidate"],
    }


def executable_active_setup():
    return {
        "signal": {"signal": "LONG", "confidence": 80},
        "risk": {"entry": 100.0, "stop_loss": 95.0, "tp1": 105.0, "tp2": 110.0, "tp3": 115.0},
        "decision": {"action": "EXECUTE"},
        "dynamic_tp": {"tp3": 115.0},
        "analysis": {"setup_quality": {"setup_fingerprint": "old-setup"}},
        "trace_id": "trace-old-active-setup",
    }


@pytest.fixture
def engine(tmp_path, monkeypatch):
    import config as config_module
    import strategy_lab

    monkeypatch.setattr(config_module.Config, "STATE_ENGINE_ENABLED", True, raising=False)
    monkeypatch.setattr(config_module.Config, "INCREMENTAL_ANALYSIS_ENABLED", False, raising=False)
    monkeypatch.setattr(strategy_lab, "_regime", lambda data: {"label": "TREND", "trend": "BULLISH", "strength": 1.0})
    monkeypatch.setattr(strategy_lab, "_trend_pullback", lambda data: dict(selected_trend_candidate()))
    monkeypatch.setattr(strategy_lab, "_risk_validate_candidate", lambda plan: {
        "eligible": True, "reason": None, "weighted_net_rr": 2.5,
        "risk_plan": {"final_geometry_reconciled": True, "risk_setup_valid": True,
                      "weighted_net_rr": 2.5, "weighted_rr": 2.7},
    })

    eng = AtlasEngine()
    state_path = tmp_path / "atlas_state_test.json"
    eng.state_engine = StateEngine(str(state_path))
    calls = {"store": 0}
    real_store = eng.state_engine.store_active_setup

    def counting_store(symbol, result, data=None):
        calls["store"] += 1
        return real_store(symbol, result, data=data)

    eng.state_engine.store_active_setup = counting_store
    eng._test_store_calls = calls
    return eng


def test_active_setup_does_not_block_fresh_five_strategy_analysis(engine):
    symbol = "BTC/USDT:USDT"
    engine.state_engine.store_active_setup(symbol, executable_active_setup())
    engine._test_store_calls["store"] = 0

    result = engine.analyze(synthetic_data(symbol))

    # Sonuç, eski aktif setup DEĞİL: taze analiz üretildi.
    assert result.get("analysis") is not None
    assert result["decision"]["decision_authority"] == "FIVE_STRATEGY_SELECTOR"
    assert result["decision"]["action"] == "EXECUTE"
    report = result["strategy_lab"]
    assert len(report["diagnostics"]["strategies"]) == 5
    assert report["selected"]["strategy_id"] == "trend_pullback"

    # Aktif setup ayrı blokta korunur; yeni sonuçla değiştirilmez.
    active = result["active_setup"]
    assert active["restored"] is True
    assert active["signal"] == "LONG"
    assert active["entry"] == 100.0
    assert active["stop_loss"] == 95.0
    assert active["trace_id"] == "trace-old-active-setup"
    # Aktif setup'ın eski trace'i yeni analizin trace'iyle karışmaz.
    assert result["trace_id"] != "trace-old-active-setup"
    assert result["trace_id"].startswith("trace-")

    # EXECUTE sonucuna rağmen mevcut aktif setup üzerine YAZILMADI.
    assert engine._test_store_calls["store"] == 0
    restored_again = engine.state_engine.get_active_setup(symbol)
    assert restored_again["trace_id"] == "trace-old-active-setup"


def test_active_setup_is_stored_only_when_none_exists(engine):
    symbol = "ETH/USDT:USDT"
    engine._test_store_calls["store"] = 0

    result = engine.analyze(synthetic_data(symbol))

    assert result["decision"]["action"] == "EXECUTE"
    # Aktif setup yokken yeni EXECUTE sonucu aktif setup olur.
    assert engine._test_store_calls["store"] == 1
    assert result.get("active_setup") is None
    stored = engine.state_engine.get_active_setup(symbol)
    assert stored is not None
    assert stored["trace_id"] == result["trace_id"]


def test_state_engine_snapshot_records_trace_id(tmp_path):
    engine = StateEngine(str(tmp_path / "state.json"))
    result = executable_active_setup()
    result["trace_id"] = "trace-stored-4242"

    snapshot = engine.store_active_setup("BTC/USDT:USDT", result)
    assert snapshot["trace_id"] == "trace-stored-4242"
