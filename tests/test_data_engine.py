import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data_engine


class FakeExchange:
    def __init__(self, rows, now_ms):
        self.rows = rows
        self.now_ms = now_ms

    def fetch_ohlcv(self, symbol, timeframe, limit):
        return self.rows

    def parse_timeframe(self, timeframe):
        return {"15m": 900, "1h": 3600, "4h": 14400}[timeframe]

    def milliseconds(self):
        return self.now_ms


def test_fetch_discards_current_incomplete_candle(monkeypatch):
    now = 10_000_000
    rows = [
        [now - 1_800_000, 100, 103, 99, 102, 10],
        [now - 900_000, 102, 105, 101, 104, 12],
    ]
    monkeypatch.setattr(data_engine, "exchange", FakeExchange(rows, now))
    candles = data_engine._fetch("BTC/USDT:USDT", "15m", 100)
    assert [c.time for c in candles] == [now - 1_800_000]


def test_fetch_discards_invalid_duplicate_and_out_of_order_rows(monkeypatch):
    now = 10_000_000
    rows = [
        [now - 3_600_000, 100, 103, 99, 102, 10],
        [now - 3_600_000, 102, 105, 101, 104, 12],
        [now - 7_200_000, 102, 105, 101, 104, 12],
        [now - 1_800_000, 100, float("nan"), 99, 102, 10],
        [now - 1_800_000, 100, 103, 99, 102, 10],
    ]
    monkeypatch.setattr(data_engine, "exchange", FakeExchange(rows, now))
    candles = data_engine._fetch("BTC/USDT:USDT", "15m", 100)
    assert len(candles) == 2
    assert candles[0].time < candles[1].time


def test_fetch_keeps_valid_closed_candle_with_zero_volume(monkeypatch):
    now = 10_000_000
    rows = [[now - 1_800_000, 100, 103, 99, 102, 0]]
    monkeypatch.setattr(data_engine, "exchange", FakeExchange(rows, now))
    candles = data_engine._fetch("BTC/USDT:USDT", "15m", 100)
    assert len(candles) == 1
    assert candles[0].volume == 0
