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



def test_fetch_history_raises_after_repeated_exchange_errors(monkeypatch):
    calls = {"count": 0}

    def fail(*args, **kwargs):
        calls["count"] += 1
        raise OSError("temporary network failure")

    monkeypatch.setattr(backtest.exchange, "fetch_ohlcv", fail)
    monkeypatch.setattr(backtest.time, "sleep", lambda *_: None)

    with pytest.raises(RuntimeError, match="4 deneme başarısız"):
        backtest._fetch_history("BTC/USDT:USDT", "15m", since_ms=0)

    assert calls["count"] == 4


def test_backtest_history_validation_rejects_insufficient_15m_data():
    data = {"15m": [_candle(i) for i in range(300)]}

    with pytest.raises(RuntimeError, match="15m geçmişi yetersiz"):
        backtest._validate_backtest_history(data, "BTC/USDT:USDT")


def test_backtest_history_validation_accepts_minimum_15m_data(capsys):
    data = {"15m": [_candle(i) for i in range(301)]}

    counts = backtest._validate_backtest_history(data, "BTC/USDT:USDT")

    assert counts["15m"] == 301
    assert "15m: 301 mum" in capsys.readouterr().out
