import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.candle import Candle
from utils.atr import atr


def _flat_candles(count=20):
    return [
        Candle(
            time=index * 15 * 60 * 1000,
            open=100.0,
            high=102.0,
            low=98.0,
            close=100.0,
            volume=10.0,
        )
        for index in range(count)
    ]


def test_atr_uses_true_range_without_network_access():
    candles = _flat_candles()

    assert atr(candles, period=14) == 4.0
    assert atr(candles, period=21) == 0
