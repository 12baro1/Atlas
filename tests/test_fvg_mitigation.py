from core.candle import Candle
from fvg_engine import FVGEngine


def _candle(open_price, high, low, close, time):
    return Candle(time=time, open=open_price, high=high, low=low, close=close, volume=1)


def test_bullish_fvg_partial_mitigation_is_not_full_fill():
    candles = [
        _candle(10, 11, 10, 10.5, 1),
        _candle(10.5, 13, 10.5, 12.5, 2),
        _candle(12, 14, 12, 13.5, 3),  # bullish FVG: 11..12
        _candle(13, 13.5, 11.5, 12, 4),  # enters 50%, not full fill
    ]
    gap = FVGEngine().detect(candles)[0]
    assert gap["filled"] is False
    assert gap["mitigation_pct"] == 50.0


def test_bullish_fvg_is_filled_only_after_far_edge_is_reached():
    candles = [
        _candle(10, 11, 10, 10.5, 1),
        _candle(10.5, 13, 10.5, 12.5, 2),
        _candle(12, 14, 12, 13.5, 3),  # bullish FVG: 11..12
        _candle(13, 13.5, 10.9, 11.2, 4),
    ]
    gap = FVGEngine().detect(candles)[0]
    assert gap["filled"] is True
    assert gap["mitigation_pct"] == 100.0


def test_bearish_fvg_partial_mitigation_is_not_full_fill():
    candles = [
        _candle(14, 14, 13, 13.5, 1),
        _candle(13.5, 13.5, 11, 11.5, 2),
        _candle(12, 12, 10, 10.5, 3),  # bearish FVG: 12..13
        _candle(10.5, 12.5, 10, 11, 4),  # enters 50%, not full fill
    ]
    gap = FVGEngine().detect(candles)[0]
    assert gap["filled"] is False
    assert gap["mitigation_pct"] == 50.0
