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
    assert backtest._history_days_for_timeframe(60, "1h") > 100
    assert backtest._history_days_for_timeframe(60, "4h") >= 226
    assert backtest._history_days_for_timeframe(60, "1d") == 560
    assert backtest._history_days_for_timeframe(60, "1w") == 2174


def test_load_historical_uses_distinct_since_dates(monkeypatch):
    now_ms = 10_000_000_000_000
    captured = {}

    def fake_fetch(symbol, timeframe, since_ms, limit):
        captured[timeframe] = (since_ms, limit)
        return []

    monkeypatch.setattr(backtest, "_fetch_history", fake_fetch)
    backtest.load_historical("BTC/USDT:USDT", days=60, now_ms=now_ms,
                             use_cache=False)

    assert captured["1w"][0] == now_ms - int(2174 * 86_400_000)
    assert captured["1w"][1] == 302
    assert captured["1d"][0] == now_ms - int(560 * 86_400_000)
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



def test_fetch_history_continues_after_short_exchange_pages(monkeypatch):
    pages = [
        [
            [1_000, 1, 2, 0, 1, 10],
            [2_000, 1, 2, 0, 1, 10],
        ],
        [
            [3_000, 1, 2, 0, 1, 10],
            [4_000, 1, 2, 0, 1, 10],
        ],
        [],
    ]
    cursors = []

    def fake_fetch(_symbol, _timeframe, cursor, _limit):
        cursors.append(cursor)
        return pages.pop(0)

    monkeypatch.setattr(backtest, "_fetch_history_batch", fake_fetch)
    monkeypatch.setattr(backtest.time, "sleep", lambda _seconds: None)

    candles = backtest._fetch_history("BTC/USDT:USDT", "15m", 1_000, limit=1_000)

    assert [item.time for item in candles] == [1_000, 2_000, 3_000, 4_000]
    assert cursors == [1_000, 2_001, 4_001]


def test_load_historical_refetches_partial_cache(monkeypatch):
    now_ms = 10_000_000_000_000
    duration = backtest.TIMEFRAME_DURATION_MS["15m"]
    since = now_ms - int(
        backtest._history_days_for_timeframe(2, "15m") * 86_400_000
    )
    stale_cache = [backtest.Candle(
        time=since + 10 * duration,
        open=1, high=2, low=1, close=2, volume=1,
    )]
    fetched = []

    monkeypatch.setattr(backtest, "TIMEFRAMES", {"15m": 1})
    monkeypatch.setattr(
        backtest, "_load_cached_candles", lambda *_args: stale_cache
    )

    def fake_fetch(_symbol, _timeframe, since_ms, limit):
        fetched.append((since_ms, limit))
        return [backtest.Candle(
            time=since_ms,
            open=1, high=2, low=1, close=2, volume=1,
        )]

    monkeypatch.setattr(backtest, "_fetch_history", fake_fetch)
    monkeypatch.setattr(backtest, "_save_cached_candles", lambda *_args: None)

    result = backtest.load_historical(
        "BTC/USDT:USDT", days=2, now_ms=now_ms, use_cache=True
    )

    assert fetched == [(since, 1)]
    assert result["15m"][0].time == since


def test_backtest_coverage_rejects_missing_requested_start(monkeypatch):
    from types import SimpleNamespace
    import pytest

    monkeypatch.setattr(
        backtest, "_history_days_for_timeframe", lambda _days, _tf: 8
    )
    monkeypatch.setattr(
        backtest, "BACKTEST_WARMUP_CANDLES",
        {"15m": 1, "1h": 1, "4h": 1, "1d": 1, "1w": 1},
    )
    now_ms = 1_700_000_000_000
    first_open = now_ms - 7 * 86_400_000
    history = {"symbol": "BTC/USDT:USDT"}
    for timeframe, duration in backtest.TIMEFRAME_DURATION_MS.items():
        history[timeframe] = [
            SimpleNamespace(time=timestamp)
            for timestamp in range(first_open, now_ms, duration)
        ]

    with pytest.raises(RuntimeError, match="istenen tarih aralığının başlangıcı eksik"):
        backtest._validate_backtest_coverage(
            history, "BTC/USDT:USDT", days=1, now_ms=now_ms
        )
