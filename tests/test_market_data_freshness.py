import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from atlas_runtime import _is_fresh_15m_data
from core.candle import Candle


def _candle(timestamp):
    return Candle(timestamp, 100.0, 101.0, 99.0, 100.5, 10.0)


def test_freshness_accepts_recent_fully_closed_15m_candle():
    candle = _candle(1_000_000)
    now_ms = candle.time + 15 * 60 * 1000 + 5 * 60 * 1000
    assert _is_fresh_15m_data([candle], now_ms, 1800) is True


def test_freshness_rejects_stale_15m_candle():
    candle = _candle(1_000_000)
    now_ms = candle.time + 15 * 60 * 1000 + 1801 * 1000
    assert _is_fresh_15m_data([candle], now_ms, 1800) is False


def test_freshness_rejects_future_or_missing_candles():
    candle = _candle(1_000_000)
    assert _is_fresh_15m_data([candle], candle.time + 10 * 60 * 1000, 1800) is False
    assert _is_fresh_15m_data([], candle.time + 20 * 60 * 1000, 1800) is False
