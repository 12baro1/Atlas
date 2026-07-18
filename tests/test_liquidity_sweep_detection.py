import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.candle import Candle
from liquidity_sweep_engine import LiquiditySweepEngine


def _candle(index, open_price, high_price, low_price, close_price):
    return Candle(
        time=1_700_000_000_000 + (index * 60_000),
        open=open_price,
        high=high_price,
        low=low_price,
        close=close_price,
        volume=100.0,
    )


def test_classifies_real_sweep_vs_breakout_and_scores_strength():
    engine = LiquiditySweepEngine()

    candles = [
        _candle(0, 99.6, 100.0, 99.2, 99.8),
        _candle(1, 99.8, 100.2, 99.5, 99.9),
        _candle(2, 99.9, 101.2, 99.6, 99.7),
    ]

    structure = [
        {
            "index": 20,
            "price": 98.5,
            "kind": "LOW",
            "label": "LL",
            "bos": True,
            "choch": False,
            "direction": "BEARISH",
        }
    ]

    layers = {
        "swing": [
            {"price": 100.0, "touches": 3, "type": "BUY_SIDE", "liquidity_kind": "SWING"},
            {"price": 98.0, "touches": 2, "type": "SELL_SIDE", "liquidity_kind": "SWING"},
        ],
        "internal": [],
    }

    result = engine.detect(
        candles=candles,
        structure=structure,
        liquidity_layers=layers,
        timeframe="15m",
    )

    assert result["is_sweep"] is True
    assert result["is_breakout"] is False
    assert result["buy_side"] is True
    assert result["post_structure"]["confirmed"] is True
    assert result["strength_score"] >= 60
    assert 0 <= result["strength_score"] <= 100


def test_detect_multi_supports_required_timeframes():
    engine = LiquiditySweepEngine()

    frame_payload = {
        "15m": {
            "candles": [_candle(0, 99, 100, 98, 99.5), _candle(1, 99.5, 101, 99, 99.4), _candle(2, 99.4, 101.2, 99, 99.2)],
            "structure": [],
            "liquidity_layers": {"swing": [{"price": 100.0, "touches": 2, "type": "BUY_SIDE", "liquidity_kind": "SWING"}], "internal": []},
        },
        "1h": {
            "candles": [_candle(0, 99, 100, 98, 99.5), _candle(1, 99.5, 101, 99, 99.4), _candle(2, 99.4, 101.2, 99, 99.2)],
            "structure": [],
            "liquidity_layers": {"swing": [{"price": 100.0, "touches": 2, "type": "BUY_SIDE", "liquidity_kind": "SWING"}], "internal": []},
        },
        "4h": {
            "candles": [_candle(0, 99, 100, 98, 99.5), _candle(1, 99.5, 101, 99, 99.4), _candle(2, 99.4, 101.2, 99, 99.2)],
            "structure": [],
            "liquidity_layers": {"swing": [{"price": 100.0, "touches": 2, "type": "BUY_SIDE", "liquidity_kind": "SWING"}], "internal": []},
        },
        "1d": {
            "candles": [_candle(0, 99, 100, 98, 99.5), _candle(1, 99.5, 101, 99, 99.4), _candle(2, 99.4, 101.2, 99, 99.2)],
            "structure": [],
            "liquidity_layers": {"swing": [{"price": 100.0, "touches": 2, "type": "BUY_SIDE", "liquidity_kind": "SWING"}], "internal": []},
        },
    }

    result = engine.detect_multi(frame_payload)

    assert "15m" in result["timeframes"]
    assert "1h" in result["timeframes"]
    assert "4h" in result["timeframes"]
    assert "1d" in result["timeframes"]
