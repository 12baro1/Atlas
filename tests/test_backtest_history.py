import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import importlib.util
from pathlib import Path

BACKTEST_SCRIPT = Path(__file__).resolve().parents[1] / "backtest.py"
spec = importlib.util.spec_from_file_location("atlas_backtest_cli", BACKTEST_SCRIPT)
backtest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backtest)

from config import Config


def test_backtest_fetches_timeframe_specific_warmup_history():
    assert backtest._history_days_for_timeframe(60, "15m") > 60
    assert backtest._history_days_for_timeframe(60, "1h") == 60
    assert backtest._history_days_for_timeframe(60, "4h") >= 166
    assert backtest._history_days_for_timeframe(60, "1d") == 500
    assert backtest._history_days_for_timeframe(60, "1w") == 2100


def test_load_historical_uses_distinct_since_dates(monkeypatch):
    now_ms = 10_000_000_000_000
    captured = {}

    def fake_fetch(symbol, timeframe, since_ms, limit):
        captured[timeframe] = (since_ms, limit)
        return []

    monkeypatch.setattr(backtest, "_fetch_history", fake_fetch)
    backtest.load_historical("BTC/USDT:USDT", days=60, now_ms=now_ms)

    assert captured["1w"][0] == now_ms - int(2100 * 86_400_000)
    assert captured["1d"][0] == now_ms - int(500 * 86_400_000)
    assert captured["15m"][0] == now_ms - int(
        backtest._history_days_for_timeframe(60, "15m") * 86_400_000
    )


def test_backtest_disables_live_features_through_environment(monkeypatch):
    names = (
        "ATLAS_STATE_ENGINE_ENABLED",
        "ATLAS_INCREMENTAL_ANALYSIS_ENABLED",
        "ATLAS_TELEGRAM_ENABLED",
        "ATLAS_CORRELATION_ENGINE_ENABLED",
        "ATLAS_ECONOMIC_NEWS_FILTER_ENABLED",
        "ATLAS_LEARNING_ENGINE_ENABLED",
        "ATLAS_SIGNAL_TRACKING_ENABLED",
        "ATLAS_TRADE_COOLDOWN_MINUTES",
        "ATLAS_AUTO_TRADING_ENABLED",
    )
    config_attrs = (
        "STATE_ENGINE_ENABLED",
        "INCREMENTAL_ANALYSIS_ENABLED",
        "TELEGRAM_ENABLED",
        "CORRELATION_ENGINE_ENABLED",
        "ECONOMIC_NEWS_FILTER_ENABLED",
        "LEARNING_ENGINE_ENABLED",
        "SIGNAL_TRACKING_ENABLED",
        "TRADE_COOLDOWN_MINUTES",
        "AUTO_TRADING_ENABLED",
    )
    # Restore process-wide Config state after this test; the real CLI exits
    # after backtest, while pytest continues running unrelated tests.
    for attr in config_attrs:
        monkeypatch.setattr(Config, attr, getattr(Config, attr))
    for name in names:
        monkeypatch.setenv(name, "1")

    backtest._disable_backtest_live_features()

    assert Config.STATE_ENGINE_ENABLED is False
    assert Config.INCREMENTAL_ANALYSIS_ENABLED is False
    assert Config.TELEGRAM_ENABLED is False
    assert Config.CORRELATION_ENGINE_ENABLED is False
    assert Config.ECONOMIC_NEWS_FILTER_ENABLED is False
    assert Config.LEARNING_ENGINE_ENABLED is False
    assert Config.SIGNAL_TRACKING_ENABLED is False
    assert Config.TRADE_COOLDOWN_MINUTES == 0.0
    assert Config.AUTO_TRADING_ENABLED is False


def test_history_days_rejects_invalid_values():
    import pytest
    with pytest.raises(ValueError):
        backtest._history_days_for_timeframe(0, "15m")
    with pytest.raises(ValueError):
        backtest._history_days_for_timeframe(60, "2h")
