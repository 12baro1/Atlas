import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.candle import Candle
from core.swing_engine import detect


def _swing_candles(count=72):
    pattern = [100, 102, 104, 106, 108, 110, 108, 106, 104, 102, 100, 98]
    candles = []
    for index in range(count):
        center = float(pattern[index % len(pattern)])
        candles.append(
            Candle(
                time=index * 15 * 60 * 1000,
                open=center - 0.25,
                high=center + 1.0,
                low=center - 1.0,
                close=center + 0.25,
                volume=100.0 + index,
            )
        )
    return candles


def test_swing_detection_is_deterministic_and_offline():
    candles = _swing_candles()

    first = detect(candles)
    second = detect(candles)

    assert len(first) >= 2
    assert [(item.index, item.price, item.kind) for item in first] == [
        (item.index, item.price, item.kind) for item in second
    ]
    assert all(0 <= item.index < len(candles) for item in first)
    assert all(item.kind in {"HIGH", "LOW"} for item in first)
