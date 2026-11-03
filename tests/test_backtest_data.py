import importlib.util
import os
from pathlib import Path

import pytest

from core.candle import Candle

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("atlas_backtest_cli", ROOT / "backtest.py")
backtest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backtest)


def _candle(timestamp):
    return Candle(time=timestamp, open=1.0, high=2.0, low=0.5, close=1.5, volume=10.0)


@pytest.mark.parametrize("timeframe", ["15m", "1h", "4h", "1d", "1w"])
def test_load_historical_excludes_unclosed_candles(monkeypatch, timeframe):
    now_ms = 10 * 24 * 60 * 60 * 1000
    duration = backtest.TIMEFRAME_DURATION_MS[timeframe]

    def fake_fetch(symbol, tf, since_ms, limit=1000):
        assert tf == timeframe
        return [_candle(now_ms - duration), _candle(now_ms - duration + 1)]

    monkeypatch.setattr(backtest, "_fetch_history", fake_fetch)
    monkeypatch.setattr(backtest, "TIMEFRAMES", {timeframe: 1000})

    data = backtest.load_historical("BTC/USDT:USDT", days=1, now_ms=now_ms)

    assert [c.time for c in data[timeframe]] == [now_ms - duration]


def test_load_historical_does_not_mutate_source_candle_list(monkeypatch):
    now_ms = 10 * 24 * 60 * 60 * 1000
    duration = backtest.TIMEFRAME_DURATION_MS["15m"]
    source = [_candle(now_ms - duration), _candle(now_ms - 1)]

    monkeypatch.setattr(backtest, "_fetch_history", lambda *args, **kwargs: source)
    monkeypatch.setattr(backtest, "TIMEFRAMES", {"15m": 1000})

    data = backtest.load_historical("BTC/USDT:USDT", days=1, now_ms=now_ms)

    assert len(source) == 2
    assert len(data["15m"]) == 1
