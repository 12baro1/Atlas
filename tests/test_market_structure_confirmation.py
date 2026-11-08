from core.candle import Candle
from core.market_structure_engine import MarketStructureEngine


def test_pivot_confirmation_index_matches_actual_right_window():
    candles = [
        Candle(time=i, open=price, high=high, low=low, close=price, volume=100)
        for i, (price, high, low) in enumerate([
            (8, 9, 7), (9, 10, 8), (10, 11, 9), (12, 13, 10),
            (10, 11, 9), (9, 10, 8), (8, 9, 7), (9, 10, 8),
        ])
    ]
    engine = MarketStructureEngine()
    pivots = engine.find_pivots(candles, left=1, right=2)
    pivot = next(item for item in pivots if item.kind == "HIGH" and item.index == 3)
    assert pivot.confirmation_index == 5


def test_pivot_strength_uses_no_candles_after_confirmation():
    candles = [
        Candle(time=i, open=10, high=value, low=value - 1, close=10, volume=100)
        for i, value in enumerate([8, 9, 10, 12, 10, 9, 8, 100, 100, 100])
    ]
    engine = MarketStructureEngine()
    pivots = engine.find_pivots(candles, left=1, right=2)
    engine.calculate_strength(candles)
    pivot = next(item for item in pivots if item.kind == "HIGH" and item.index == 3)
    strength_before = pivot.strength
    candles[7].high = -100
    engine.calculate_strength(candles)
    assert pivot.strength == strength_before
