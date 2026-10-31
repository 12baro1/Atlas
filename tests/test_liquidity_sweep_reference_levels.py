from core.candle import Candle
from liquidity_sweep_engine import LiquiditySweepEngine


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
