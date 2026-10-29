import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.candle import Candle
from core.market_structure_engine import MarketStructureEngine


def _synthetic_candles(count=80):
    """Build deterministic OHLCV data so tests never depend on a live exchange."""
    candles = []
    for index in range(count):
        center = 100.0 + ((index % 12) - 6) * 1.5
        open_price = center - 0.25
        close_price = center + 0.25
        candles.append(
            Candle(
                time=index * 15 * 60 * 1000,
                open=open_price,
                high=center + 1.0,
                low=center - 1.0,
                close=close_price,
                volume=100.0 + index,
            )
        )
    return candles


def test_market_structure_pipeline_runs_offline():
    candles = _synthetic_candles()
    engine = MarketStructureEngine()

    engine.find_pivots(candles, left=2, right=2)
    engine.calculate_strength(candles)
    engine.merge_pivots()
    engine.filter_noise(min_strength=1)
    pivots = engine.validate_sequence()

    assert isinstance(pivots, list)
    assert all(pivot.kind in {"HIGH", "LOW"} for pivot in pivots)
    assert all(0 <= pivot.index < len(candles) for pivot in pivots)


def test_find_pivots_resets_previous_results():
    candles = _synthetic_candles()
    engine = MarketStructureEngine()

    first = engine.find_pivots(candles, left=2, right=2)
    second = engine.find_pivots(candles, left=2, right=2)

    assert len(second) == len(first)
    assert second is engine.pivots
