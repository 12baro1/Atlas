import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.candle import Candle
from fvg_engine import FVGEngine
from orderblock_engine import OrderBlockEngine


def _candle(timestamp, open_price, high, low, close):
    return Candle(
        time=timestamp,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=100.0,
    )


def test_fvg_event_identity_uses_creation_candle_timestamp():
    candles = [
        _candle(1_700_000_000_000, 99.0, 100.0, 98.0, 99.5),
        _candle(1_700_000_060_000, 99.5, 102.0, 99.0, 101.5),
        _candle(1_700_000_120_000, 102.0, 104.0, 102.0, 103.5),
    ]
    gaps = FVGEngine().detect(candles)
    bullish = next(item for item in gaps if item["type"] == "BULLISH")
    assert bullish["event_id"].startswith("fvg:FVG:BULLISH:1700000120000:")


def test_orderblock_event_identity_uses_origin_candle_timestamp():
    candles = [
        _candle(1_700_000_000_000, 100.0, 101.0, 99.0, 100.5),
        _candle(1_700_000_060_000, 100.5, 101.0, 98.0, 98.5),
        _candle(1_700_000_120_000, 98.5, 103.0, 98.0, 102.5),
    ]
    structure = [{
        "bos": True,
        "index": 2,
        "break_index": 3,
        "direction": "BULLISH",
        "label": "HH",
    }]
    blocks = OrderBlockEngine().detect(candles, structure)
    assert blocks
    assert blocks[0]["index"] == 1
    assert blocks[0]["event_id"].startswith("orderblock:BULLISH:1700000060000:")
