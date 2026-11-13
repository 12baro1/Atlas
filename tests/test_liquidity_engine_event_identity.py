import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.candle import Candle
from liquidity_engine import LiquidityEngine


def _candles(start_time, count):
    return [
        Candle(
            time=start_time + index * 60_000,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            volume=100.0,
        )
        for index in range(count)
    ]


def test_swing_liquidity_pool_identity_uses_confirmed_pivot_timestamps():
    candles = _candles(1_700_000_000_000, 5)
    structure = [
        {"kind": "HIGH", "index": 1, "confirmation_index": 2, "price": 105.0},
        {"kind": "HIGH", "index": 3, "confirmation_index": 4, "price": 105.02},
    ]
    result = LiquidityEngine().detect_layers(structure, candles)
    pool = result["bsl"][0]
    assert pool["touches"] == 2
    assert pool["event_id"].startswith("liquidity:SWING:BUY_SIDE:1700000060000:1700000180000:")
