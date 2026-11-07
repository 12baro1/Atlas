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


def test_market_listing_time_reads_bybit_launch_timestamp(monkeypatch):
    class FakeExchange:
        def load_markets(self):
            return {
                "ETH/USDT:USDT": {
                    "info": {"launchTime": "1615766400000"}
                }
            }

    monkeypatch.setattr(backtest, "exchange", FakeExchange())

    assert backtest._market_listing_time_ms("ETH/USDT:USDT") == 1615766400000


def test_load_historical_clamps_since_to_market_listing(monkeypatch):
    now_ms = 2_000_000_000_000
    listing_time_ms = now_ms - 50 * 86_400_000
    seen = []

    def fake_fetch(symbol, timeframe, since_ms, limit=1000):
        seen.append((timeframe, since_ms))
        return []

    monkeypatch.setattr(backtest, "_fetch_history", fake_fetch)
    monkeypatch.setattr(backtest, "TIMEFRAMES", {"1w": 300, "1d": 500})

    backtest.load_historical(
        "ETH/USDT:USDT", days=1, now_ms=now_ms,
        listing_time_ms=listing_time_ms,
    )

    assert all(since == listing_time_ms for _, since in seen)


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



def _complete_coverage_data(days, now_ms):
    data = {}
    for timeframe, duration in backtest.TIMEFRAME_DURATION_MS.items():
        history_days = backtest._history_days_for_timeframe(days, timeframe)
        requested_start = now_ms - history_days * 86_400_000
        first_open = int(requested_start // duration) * duration
        last_open = (int(now_ms // duration) - 1) * duration
        data[timeframe] = [
            _candle(timestamp)
            for timestamp in range(first_open, last_open + 1, duration)
        ]
    return data


def test_backtest_coverage_accepts_full_requested_history(capsys):
    now_ms = 2_000_000_000_000
    data = _complete_coverage_data(days=2, now_ms=now_ms)

    coverage = backtest._validate_backtest_coverage(
        data, "BTC/USDT:USDT", days=2, now_ms=now_ms
    )

    assert set(coverage) == {"15m", "1h", "4h", "1d", "1w"}
    assert "TARİH KAPSAMI" in capsys.readouterr().out


def test_backtest_coverage_accepts_listing_limited_weekly_warmup(capsys):
    now_ms = 2_000_000_000_000
    days = 7
    listing_time_ms = now_ms - 295 * backtest.TIMEFRAME_DURATION_MS["1w"]
    data = _complete_coverage_data(days=days, now_ms=now_ms)
    weekly_duration = backtest.TIMEFRAME_DURATION_MS["1w"]
    first_weekly = int(listing_time_ms // weekly_duration) * weekly_duration
    last_weekly = (int(now_ms // weekly_duration) - 1) * weekly_duration
    data["1w"] = [
        _candle(timestamp)
        for timestamp in range(first_weekly, last_weekly + 1, weekly_duration)
    ]

    coverage = backtest._validate_backtest_coverage(
        data, "ETH/USDT:USDT", days=days, now_ms=now_ms,
        listing_time_ms=listing_time_ms,
    )

    assert coverage["1w"]["count"] < backtest.BACKTEST_WARMUP_CANDLES["1w"]
    assert coverage["1w"]["warmup_reduced"] is True
    assert "WARMUP UYARISI" in capsys.readouterr().out


def test_backtest_coverage_keeps_full_weekly_warmup_without_listing_limit():
    now_ms = 2_000_000_000_000
    data = _complete_coverage_data(days=7, now_ms=now_ms)
    data["1w"] = data["1w"][-250:]

    with pytest.raises(RuntimeError, match="1w: warmup verisi yetersiz"):
        backtest._validate_backtest_coverage(
            data, "BTC/USDT:USDT", days=7, now_ms=now_ms
        )


def test_backtest_coverage_rejects_late_start():
    now_ms = 2_000_000_000_000
    data = _complete_coverage_data(days=2, now_ms=now_ms)
    data["4h"] = data["4h"][10:]

    with pytest.raises(RuntimeError, match="başlangıç verisi eksik"):
        backtest._validate_backtest_coverage(
            data, "BTC/USDT:USDT", days=2, now_ms=now_ms
        )


def test_backtest_coverage_rejects_large_internal_gap():
    now_ms = 2_000_000_000_000
    data = _complete_coverage_data(days=2, now_ms=now_ms)
    candles = data["1h"]
    data["1h"] = candles[:100] + candles[103:]

    with pytest.raises(RuntimeError, match="veri boşluğu"):
        backtest._validate_backtest_coverage(
            data, "BTC/USDT:USDT", days=2, now_ms=now_ms
        )


def test_backtest_coverage_rejects_stale_latest_candle():
    now_ms = 2_000_000_000_000
    data = _complete_coverage_data(days=2, now_ms=now_ms)
    data["15m"] = data["15m"][:-20]

    with pytest.raises(RuntimeError, match="son mum eski"):
        backtest._validate_backtest_coverage(
            data, "BTC/USDT:USDT", days=2, now_ms=now_ms
        )


def test_fetch_history_clears_transient_error_after_success(monkeypatch):
    calls = {"count": 0}

    def fetch(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise OSError("temporary network failure")
        if calls["count"] == 2:
            return [[60_000, 1.0, 2.0, 0.5, 1.5, 10.0]]
        return []

    monkeypatch.setattr(backtest.exchange, "fetch_ohlcv", fetch)
    monkeypatch.setattr(backtest.time, "sleep", lambda *_: None)

    candles = backtest._fetch_history("BTC/USDT:USDT", "1m", since_ms=0)

    assert len(candles) == 1
    assert candles[0].time == 60_000
    assert calls["count"] == 2



def test_fetch_history_uses_binance_fallback_after_bybit_geoblock(monkeypatch):
    calls = {"bybit": 0, "fallback": 0}

    def blocked(*args, **kwargs):
        calls["bybit"] += 1
        raise RuntimeError("403 Forbidden CloudFront distribution is configured to block")

    class FakeFallback:
        def fetch_ohlcv(self, *args, **kwargs):
            calls["fallback"] += 1
            if calls["fallback"] == 1:
                return [[60_000, 1.0, 2.0, 0.5, 1.5, 10.0]]
            return []

    monkeypatch.setattr(backtest.exchange, "fetch_ohlcv", blocked)
    monkeypatch.setattr(backtest, "_create_history_fallback_exchange", FakeFallback)
    monkeypatch.setattr(backtest.time, "sleep", lambda *_: None)
    monkeypatch.setattr(backtest, "_history_fallback_exchange", None)
    monkeypatch.setattr(backtest, "_history_provider_name", "Bybit")

    candles = backtest._fetch_history("BTC/USDT:USDT", "1m", since_ms=0)

    assert len(candles) == 1
    assert calls["bybit"] == 1
    assert calls["fallback"] == 1
    assert "Binance USD-M Futures" in backtest._history_provider_name


def test_fetch_history_does_not_switch_provider_for_transient_errors(monkeypatch):
    monkeypatch.setattr(backtest, "_history_fallback_exchange", None)
    monkeypatch.setattr(backtest.exchange, "fetch_ohlcv", lambda *a, **k: (_ for _ in ()).throw(OSError("temporary")))
    monkeypatch.setattr(backtest.time, "sleep", lambda *_: None)

    with pytest.raises(RuntimeError, match="4 deneme başarısız"):
        backtest._fetch_history("BTC/USDT:USDT", "15m", since_ms=0)
