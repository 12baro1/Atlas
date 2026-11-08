from core.candle import Candle
from breaker_block_engine import BreakerBlockEngine


def test_failed_bullish_order_block_becomes_bearish_breaker():
    candles = [
        Candle(time=0, open=100, high=102, low=99, close=101, volume=10),
        Candle(time=1, open=101, high=102, low=94, close=95, volume=10),
    ]
    result = BreakerBlockEngine().detect(candles, [{
        "type": "BULLISH", "index": 0, "low": 98, "high": 100, "strength": 70,
    }])
    assert len(result) == 1
    assert result[0]["type"] == "BEARISH"
    assert result[0]["original_type"] == "BULLISH"
    assert result[0]["direction"] == "BEARISH"
    assert result[0]["break_index"] == 1


def test_failed_bearish_order_block_becomes_bullish_breaker():
    candles = [
        Candle(time=0, open=100, high=102, low=99, close=101, volume=10),
        Candle(time=1, open=101, high=106, low=100, close=105, volume=10),
    ]
    result = BreakerBlockEngine().detect(candles, [{
        "type": "BEARISH", "index": 0, "low": 102, "high": 104, "strength": 70,
    }])
    assert len(result) == 1
    assert result[0]["type"] == "BULLISH"
    assert result[0]["original_type"] == "BEARISH"
    assert result[0]["direction"] == "BULLISH"
