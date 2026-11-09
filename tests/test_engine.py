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


def test_default_noise_filter_keeps_pivots_with_normal_confirmation_strength():
    candles = _synthetic_candles()
    engine = MarketStructureEngine()
    engine.find_pivots(candles, left=2, right=2)
    engine.calculate_strength(candles)

    before_filter = len(engine.pivots)
    kept = engine.filter_noise()

    assert before_filter > 0
    assert kept
    assert all(pivot.confirmed and pivot.strength >= 3 for pivot in kept)


def test_pivot_windows_reject_invalid_values():
    import pytest

    engine = MarketStructureEngine()
    with pytest.raises(ValueError):
        engine.find_pivots(_synthetic_candles(), left=0, right=2)
    with pytest.raises(ValueError):
        engine.find_pivots(_synthetic_candles(), left=2, right=-1)


def test_strength_is_bounded_to_configured_pivot_context():
    candles = _synthetic_candles()
    engine = MarketStructureEngine()
    pivots = engine.find_pivots(candles, left=2, right=2)
    engine.calculate_strength(candles)

    assert all(pivot.strength <= 4 for pivot in pivots)


def test_pivot_strength_measures_prominence_not_just_local_extremum():
    candles = [
        Candle(time=0, open=99, high=99.0, low=97.0, close=98.0, volume=1),
        Candle(time=1, open=99, high=99.9, low=97.9, close=98.5, volume=1),
        Candle(time=2, open=99, high=100.0, low=98.0, close=99.0, volume=1),
        Candle(time=3, open=99, high=99.95, low=97.95, close=98.5, volume=1),
        Candle(time=4, open=99, high=99.9, low=97.9, close=98.5, volume=1),
    ]
    engine = MarketStructureEngine()
    pivots = engine.find_pivots(candles, left=2, right=2)
    engine.calculate_strength(candles)
    high_pivot = next(pivot for pivot in pivots if pivot.kind == "HIGH")

    assert high_pivot.strength < 4
    assert engine.filter_noise(min_strength=3) == []
