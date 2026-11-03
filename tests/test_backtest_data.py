import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backtest
from core.candle import Candle


def _candle(timestamp):
    return Candle(time=timestamp, open=1.0, high=2.0, low=0.5, close=1.5, volume=10.0)


def test_load_historical_excludes_unclosed_candles(monkeypatch):
    now_ms = 10 * 60 * 60 * 1000
    captured = {}

    def fake_fetch(symbol, timeframe, since_ms, limit=1000):
        duration = backtest.TIMEFRAME_DURATION_MS[timeframe]
        # One candle closed exactly at as-of, one is still forming.
        return [
            _candle(now_ms - duration),
            _candle(now_ms - duration + 1),
        ]

    monkeypatch.setattr(backtest, "_fetch_history", fake_fetch)
    monkeypatch.setattr(backtest, "TIMEFRAMES", {"15m": 1000, "1h": 1000})

    data = backtest.load_historical("BTC/USDT:USDT", days=1, now_ms=now_ms)

    assert [c.time for c in data["15m"]] == [now_ms - backtest.TIMEFRAME_DURATION_MS["15m"]]
    assert [c.time for c in data["1h"]] == [now_ms - backtest.TIMEFRAME_DURATION_MS["1h"]]


def test_load_historical_does_not_mutate_source_candle_list(monkeypatch):
    now_ms = 10 * 60 * 60 * 1000
    source = [_candle(now_ms - 15 * 60 * 1000), _candle(now_ms - 1)]

    monkeypatch.setattr(backtest, "_fetch_history", lambda *args, **kwargs: source)
    monkeypatch.setattr(backtest, "TIMEFRAMES", {"15m": 1000})

    data = backtest.load_historical("BTC/USDT:USDT", days=1, now_ms=now_ms)

    assert len(source) == 2
    assert len(data["15m"]) == 1
