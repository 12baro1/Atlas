from core.candle import Candle
from liquidity_sweep_engine import LiquiditySweepEngine
from liquidity_engine import LiquidityEngine


def _candle(open_price, high, low, close):
    return Candle(time=1_700_000_000_000, open=open_price, high=high, low=low, close=close, volume=1)


def test_nearest_levels_only_uses_liquidity_still_ahead_of_previous_close():
    engine = LiquiditySweepEngine()
    previous = _candle(99.0, 100.0, 98.0, 99.5)
    levels = [
        {"type": "BUY_SIDE", "price": 98.0},
        {"type": "BUY_SIDE", "price": 101.0},
        {"type": "SELL_SIDE", "price": 100.0},
        {"type": "SELL_SIDE", "price": 97.0},
    ]
    buy, sell = engine._nearest_levels(levels, previous)
    assert buy["price"] == 101.0
    assert sell["price"] == 97.0


def test_already_crossed_levels_cannot_be_misclassified_as_fresh_sweeps():
    engine = LiquiditySweepEngine()
    candles = [
        _candle(99.0, 100.0, 98.0, 99.5),
        _candle(99.5, 101.5, 99.0, 101.0),
        _candle(101.0, 102.0, 100.5, 101.5),
    ]
    layers = {
        "swing": [
            {"type": "BUY_SIDE", "price": 100.0},
            {"type": "SELL_SIDE", "price": 98.0},
        ],
        "internal": [],
    }
    result = engine.detect(candles, liquidity_layers=layers)
    assert result["buy_side"] is False
    assert result["sell_side"] is False


def test_previous_wick_consumes_buy_side_level_even_when_close_returns_below():
    engine = LiquiditySweepEngine()
    previous = _candle(99.0, 100.5, 98.5, 99.5)
    levels = [
        {"type": "BUY_SIDE", "price": 100.0},
        {"type": "SELL_SIDE", "price": 97.0},
    ]

    buy, sell = engine._nearest_levels(levels, previous)

    assert buy is None
    assert sell["price"] == 97.0


def test_previous_wick_consumes_sell_side_level_even_when_close_returns_above():
    engine = LiquiditySweepEngine()
    previous = _candle(99.0, 101.0, 98.5, 100.0)
    levels = [
        {"type": "BUY_SIDE", "price": 102.0},
        {"type": "SELL_SIDE", "price": 99.0},
    ]

    buy, sell = engine._nearest_levels(levels, previous)

    assert buy["price"] == 102.0
    assert sell is None


def test_filtered_old_liquidity_does_not_fall_back_to_previous_candle_extremes():
    engine = LiquiditySweepEngine()
    candles = [
        _candle(99.0, 101.0, 98.0, 99.5),
        # The prior candle has already wicked through BSL=100.
        _candle(99.5, 100.5, 99.0, 99.6),
        # This candle re-crosses that old level but does not sweep prev.high.
        _candle(99.6, 100.2, 99.2, 99.4),
    ]
    layers = {
        "swing": [{"type": "BUY_SIDE", "price": 100.0}],
        "internal": [],
    }

    result = engine.detect(candles, liquidity_layers=layers)

    assert result["buy_side"] is False
    assert result["is_sweep"] is False


def test_filtered_old_sell_side_liquidity_does_not_trigger_legacy_fallback():
    engine = LiquiditySweepEngine()
    candles = [
        _candle(100.0, 102.0, 99.0, 100.5),
        # The prior candle has already wicked through SSL=100.
        _candle(100.5, 101.0, 99.5, 100.4),
        # This candle re-crosses that old level but does not sweep prev.low.
        _candle(100.4, 100.8, 99.8, 100.6),
    ]
    layers = {
        "swing": [{"type": "SELL_SIDE", "price": 100.0}],
        "internal": [],
    }

    result = engine.detect(candles, liquidity_layers=layers)

    assert result["sell_side"] is False
    assert result["is_sweep"] is False


def test_exact_level_touch_does_not_consume_liquidity_pool():
    engine = LiquiditySweepEngine()
    previous = _candle(99.0, 100.0, 98.0, 99.5)
    levels = [
        {"type": "BUY_SIDE", "price": 100.0},
        {"type": "SELL_SIDE", "price": 98.0},
    ]

    buy, sell = engine._nearest_levels(levels, previous)

    assert buy["price"] == 100.0
    assert sell["price"] == 98.0



def test_liquidity_cluster_records_second_touch_confirmation_index():
    engine = LiquidityEngine()
    structure = [
        {"kind": "HIGH", "price": 100.0, "index": 2, "confirmation_index": 7},
        {"kind": "HIGH", "price": 100.05, "index": 8, "confirmation_index": 13},
    ]

    [cluster] = engine.detect(structure)

    assert cluster["touches"] == 2
    assert cluster["indices"] == [2, 8]
    assert cluster["confirmation_indices"] == [7, 13]
    assert cluster["formed_at"] == 13


def test_internal_liquidity_points_include_confirmation_index():
    engine = LiquidityEngine()
    candles = [
        _candle(100, 102, 99, 101),
        _candle(101, 104, 100, 103),
        _candle(103, 103, 98, 100),
        _candle(100, 102, 99, 101),
        _candle(101, 103, 100, 102),
    ]

    points = engine._extract_internal_points(candles)

    assert points
    assert all("index" in point for point in points)
    assert all(point["confirmation_index"] == point["index"] + 1 for point in points)



def test_pool_swept_while_equal_high_cluster_is_forming_is_not_reused():
    engine = LiquiditySweepEngine()
    candles = [
        _candle(99.0, 100.0, 98.8, 99.5),   # first equal-high touch
        _candle(99.5, 99.8, 99.0, 99.4),
        _candle(99.4, 100.3, 99.1, 99.5),   # pool taken before confirmation
        _candle(99.5, 99.8, 99.0, 99.4),
        _candle(99.4, 99.7, 99.1, 99.5),
        _candle(99.5, 100.0, 99.2, 99.6),   # second equal-high touch
        _candle(99.6, 99.9, 99.3, 99.7),    # pool becomes confirmed
        _candle(99.7, 100.4, 99.4, 99.6),   # looks like a fresh sweep, but isn't
    ]
    layers = {
        "swing": [{
            "type": "BUY_SIDE",
            "price": 100.0,
            "touches": 2,
            "indices": [0, 5],
            "formed_at": 6,
            "liquidity_kind": "SWING",
        }],
        "internal": [],
    }

    result = engine.detect(candles, liquidity_layers=layers)

    assert result["is_sweep"] is False
