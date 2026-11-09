"""Canonical candle value object and tolerant OHLCV row conversion."""

from dataclasses import dataclass
from datetime import datetime
import math


@dataclass
class Candle:
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def bullish(self):
        return self.close > self.open

    @property
    def bearish(self):
        return self.close < self.open

    @property
    def body(self):
        return abs(self.close - self.open)

    @property
    def range(self):
        return self.high - self.low

    @property
    def upper_wick(self):
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self):
        return min(self.open, self.close) - self.low

    @property
    def date(self):
        return datetime.fromtimestamp(self.time / 1000)


def convert(data):
    """Convert exchange OHLCV rows, skipping malformed or impossible candles."""
    candles = []
    for row in data or []:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        try:
            timestamp = int(row[0])
            open_price, high, low, close, volume = (float(value) for value in row[1:6])
        except (TypeError, ValueError, OverflowError):
            continue

        values = (open_price, high, low, close, volume)
        if timestamp < 0 or not all(math.isfinite(value) for value in values):
            continue
        if min(open_price, high, low, close) <= 0 or volume < 0:
            continue
        if high < max(open_price, close, low) or low > min(open_price, close, high):
            continue
        candles.append(Candle(
            time=timestamp,
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=volume,
        ))
    return candles
