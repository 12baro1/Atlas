import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.candle import convert


def test_convert_and_candle_ohlc_properties():
    candles = convert([
        [0, 100.0, 105.0, 98.0, 103.0, 10.0],
        [900_000, 103.0, 107.0, 101.0, 102.0, 12.0],
    ])

    assert len(candles) == 2
    first, second = candles
    assert first.bullish is True
    assert first.bearish is False
    assert first.body == 3.0
    assert first.range == 7.0
    assert first.upper_wick == 2.0
    assert first.lower_wick == 2.0
    assert second.bearish is True
    assert second.body == 1.0
    assert second.upper_wick == 4.0
    assert second.lower_wick == 1.0


def test_convert_normalizes_numeric_strings_and_skips_invalid_rows():
    candles = convert([
        ["1000", "100", "105", "98", "103", "10"],
        [2000, "100", "97", "98", "99", "10"],  # high below open
        [3000, "nan", "105", "98", "103", "10"],
        [4000, "100", "105", "98", "103", "-1"],
        [5000, 100, 105, 98, 103, 10],
    ])

    assert len(candles) == 2
    assert candles[0].time == 1000
    assert candles[0].open == 100.0
    assert candles[1].time == 5000
