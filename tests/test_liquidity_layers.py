import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.candle import Candle
from liquidity_engine import LiquidityEngine


def _candles(prices):
    rows = []
    base = 1_700_000_000_000

    for i, value in enumerate(prices):
        rows.append(
            Candle(
                time=base + (i * 60_000),
                open=value,
                high=value + 0.6,
                low=value - 0.6,
                close=value + 0.1,
                volume=100.0,
            )
        )

    return rows


def test_detect_layers_builds_bsl_ssl_and_eq_clusters():
    engine = LiquidityEngine()

    structure = [
        {"kind": "HIGH", "price": 100.0},
        {"kind": "HIGH", "price": 100.03},
        {"kind": "LOW", "price": 90.0},
        {"kind": "LOW", "price": 90.02},
        {"kind": "HIGH", "price": 100.01},
        {"kind": "LOW", "price": 89.99},
    ]

    candles = _candles([95, 96, 95.5, 96.4, 95.8, 96.2, 95.7, 96.3, 95.9, 96.1])

    layers = engine.detect_layers(structure, candles)

    assert layers["bsl"]
    assert layers["ssl"]
    assert layers["eqh"]
    assert layers["eql"]

    assert any(item["liquidity_kind"] == "SWING" for item in layers["all"])
    assert isinstance(layers["internal"], list)
