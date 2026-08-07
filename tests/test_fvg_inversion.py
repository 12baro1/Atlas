"""Test suite for Inverse FVG (IFVG) detection in FVGEngine."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.candle import Candle
from fvg_engine import FVGEngine


def c(time, open_, high, low, close, volume=0):
    return Candle(time, open_, high, low, close, volume)


def test_bullish_fvg_inversion_detected():
    engine = FVGEngine()
    # 3'lü bölge: gap yukarı (bullish FVG), ardından fiyat bölgeyi doldurur
    candles = [
        c(0, 100, 102, 99, 101),
        c(1, 101, 101.5, 100.5, 101),
        c(2, 101, 104, 101, 103),      # left.high=102 < right.low=101? hayır -> farklı; bunu düzeltelim
    ]
    # Net bir bullish FVG için: left.high < right.low
    candles = [
        c(0, 100, 103, 100, 102),      # left.high=103
        c(1, 102, 102.5, 101.5, 102),  # mid
        c(2, 102, 105, 101, 104),      # right.low=101 -> 103 < 101 FALSE (bullish gap yok)
    ]
    candles = [
        c(0, 100, 102, 100, 101),      # left.high=102
        c(1, 101, 101.5, 100.5, 101),
        c(2, 102, 104, 103, 103.5),    # right.low=103 -> 102<103 TRUE bullish gap [102,103]
        c(3, 103.5, 103.8, 101.5, 102.5),  # fiyat ine gap'i doldurur (hit 102-103)
    ]

    inversions = engine.detect_inversion(candles)

    assert len(inversions) == 1
    inv = inversions[0]
    assert inv["inverted"] is True
    assert inv["type"] == "BULLISH"


def test_no_inversion_when_gap_not_filled():
    engine = FVGEngine()
    candles = [
        c(0, 100, 102, 100, 101),
        c(1, 101, 101.5, 100.5, 101),
        c(2, 102, 104, 103, 103.5),   # bullish gap [102,103]
        c(3, 103.5, 106, 103.5, 105), # hiç bölgeye inmez -> inversiyon yok
    ]

    inversions = engine.detect_inversion(candles)

    assert inversions == []


def test_insufficient_candles_returns_empty():
    engine = FVGEngine()
    assert engine.detect_inversion([]) == []
    assert engine.detect_inversion([c(0, 1, 2, 0, 1), c(1, 1, 2, 0, 1), c(2, 1, 2, 0, 1)]) == []