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
