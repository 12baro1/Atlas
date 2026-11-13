import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.candle import Candle
from market_phase_engine import MarketPhaseEngine


def test_market_phase_snapshot_identity_includes_timeframe_and_candle_time():
    candles = [
        Candle(
            time=1_700_000_000_000 + index * 60_000,
            open=100.0,
            high=102.0,
            low=98.0,
            close=101.0,
            volume=100.0,
        )
        for index in range(3)
    ]
    result = MarketPhaseEngine().detect(
        structure=[],
        trend={"trend": "RANGE", "strength": 0},
        liquidity_sweep={},
        fvg=[],
        orderblocks=[],
        premium_discount={"valid": False, "premium": False, "discount": False},
        mtf={"valid": False},
        candles=candles,
        timeframe="1h",
    )
    assert result["event_id"] == "market_phase:1h:snapshot:1700000120000"
