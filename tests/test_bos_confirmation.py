from core.candle import Candle
from bos_engine import BOSEngine
from orderblock_engine import OrderBlockEngine


def _candles(closes, highs=None, lows=None):
    highs = highs or [value + 1 for value in closes]
    lows = lows or [value - 1 for value in closes]
    return [
        Candle(time=i, open=value, high=highs[i], low=lows[i], close=value, volume=100)
        for i, value in enumerate(closes)
    ]


def _pivots():
    return [
        {"index": 1, "price": 10.0, "type": "HIGH", "label": "LH", "confirmation_index": 2},
        {"index": 3, "price": 8.0, "type": "LOW", "label": "LL", "confirmation_index": 4},
        {"index": 6, "price": 12.0, "type": "HIGH", "label": "HH", "confirmation_index": 7},
    ]


def test_bos_requires_a_close_beyond_the_previous_swing():
    candles = _candles([9.0, 9.5, 9.0, 9.2, 9.6, 10.2, 11.0])
    result = BOSEngine().detect(_pivots(), candles=candles)
    event = result[-1]
    assert event["bos"] is True
    assert event["direction"] == "BULLISH"
    assert event["break_index"] == 5


def test_wick_through_without_close_does_not_confirm_bos():
    candles = _candles(
        [9.0, 9.5, 9.0, 9.2, 9.6, 9.8, 9.9],
        highs=[10.0, 10.0, 9.5, 9.8, 10.1, 12.5, 12.0],
    )
    result = BOSEngine().detect(_pivots(), candles=candles)
    assert result[-1]["bos"] is False
    assert result[-1]["break_index"] is None


def test_order_block_uses_last_opposing_candle_before_break():
    candles = [
        Candle(time=0, open=9.0, high=9.5, low=8.5, close=9.2, volume=100),
        Candle(time=1, open=9.2, high=9.8, low=9.0, close=9.6, volume=100),
        Candle(time=2, open=9.6, high=9.7, low=9.0, close=9.1, volume=100),
        Candle(time=3, open=9.1, high=9.8, low=9.0, close=9.7, volume=100),
        Candle(time=4, open=9.7, high=10.0, low=9.2, close=9.3, volume=100),
        Candle(time=5, open=9.3, high=10.8, low=9.2, close=10.5, volume=100),
        Candle(time=6, open=10.5, high=11.0, low=10.2, close=10.8, volume=100),
    ]
    blocks = OrderBlockEngine().detect(candles, [{
        "index": 6, "break_index": 5, "label": "HH",
        "bos": True, "direction": "BULLISH",
    }])
    assert len(blocks) == 1
    assert blocks[0]["index"] == 4
    assert blocks[0]["low"] == candles[4].low
