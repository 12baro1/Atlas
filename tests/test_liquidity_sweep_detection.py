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
            {"price": 100.5, "touches": 3, "type": "BUY_SIDE", "liquidity_kind": "SWING"},
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
    assert result["post_structure"]["confirmed"] is False
    assert result["post_structure"]["reason"] == "post_sweep_structure_break_missing"
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


def test_post_structure_confirmation_requires_break_after_sweep():
    engine = LiquiditySweepEngine()
    candles = [
        _candle(0, 99.6, 100.0, 99.2, 99.8),
        _candle(1, 99.8, 100.2, 99.5, 99.9),
        _candle(2, 99.9, 101.2, 99.6, 99.7),
    ]
    structure = [{
        "index": 20, "price": 98.5, "kind": "LOW", "label": "LL",
        "bos": True, "choch": False, "direction": "BEARISH",
        "break_index": 1,
    }]
    layers = {
        "swing": [{"price": 100.5, "touches": 3, "type": "BUY_SIDE", "liquidity_kind": "SWING"}],
        "internal": [],
    }
    result = engine.detect(candles, structure, layers)
    assert result["buy_side"] is True
    assert result["post_structure"]["confirmed"] is False
    assert result["post_structure"]["reason"] == "post_sweep_structure_break_missing"


def test_post_structure_confirmation_rejects_unobserved_future_break_index():
    engine = LiquiditySweepEngine()
    candles = [
        _candle(0, 99.6, 100.0, 99.2, 99.8),
        _candle(1, 99.8, 100.2, 99.5, 99.9),
        _candle(2, 99.9, 101.2, 99.6, 99.7),
    ]
    structure = [{
        "index": 20, "price": 98.5, "kind": "LOW", "label": "LL",
        "bos": True, "choch": False, "direction": "BEARISH",
        "break_index": 3,
    }]
    layers = {
        "swing": [{"price": 100.5, "touches": 3, "type": "BUY_SIDE", "liquidity_kind": "SWING"}],
        "internal": [],
    }
    result = engine.detect(candles, structure, layers)
    assert result["post_structure"]["confirmed"] is False
    assert result["post_structure"]["reason"] == "post_sweep_structure_break_missing"



def _multi_candle_sweep_series():
    return [
        _candle(0, 99.4, 99.8, 99.0, 99.5),
        _candle(1, 99.5, 99.9, 99.1, 99.6),
        _candle(2, 99.6, 99.9, 99.2, 99.7),
        _candle(3, 99.7, 100.5, 99.4, 99.8),  # BSL sweep
        _candle(4, 99.8, 100.0, 99.4, 99.7),
        _candle(5, 99.7, 99.8, 99.0, 99.4),   # post-sweep swing low
        _candle(6, 99.4, 99.7, 99.2, 99.3),
        _candle(7, 99.3, 99.6, 99.1, 99.2),   # pivot confirmation window ends
        _candle(8, 99.2, 99.5, 98.8, 98.9),   # close breaks the swing low
    ]


def test_sweep_is_retained_and_confirmed_by_a_later_close_through_post_sweep_swing():
    engine = LiquiditySweepEngine()
    result = engine.detect(
        candles=_multi_candle_sweep_series(),
        structure=[{
            "index": 5, "price": 99.0, "kind": "LOW", "label": "HL",
            "confirmation_index": 7, "bos": False, "choch": False,
        }],
        liquidity_layers={
            "swing": [{
                "price": 100.0, "touches": 2, "type": "BUY_SIDE",
                "liquidity_kind": "SWING", "formed_at": 1,
            }],
            "internal": [],
        },
    )

    assert result["is_sweep"] is True
    assert result["sweep_index"] == 3
    assert result["sweep_age_bars"] == 5
    assert result["post_structure"]["confirmed"] is True
    assert result["post_structure"]["direction"] == "BEARISH"
    assert result["post_structure"]["type"] == "CHOCH"
    assert result["post_structure"]["confirmation_index"] == 8


def test_sweep_does_not_confirm_on_wick_only_break_of_post_sweep_pivot():
    engine = LiquiditySweepEngine()
    candles = _multi_candle_sweep_series()
    candles[-1] = _candle(8, 99.2, 99.5, 98.8, 99.05)
    result = engine.detect(
        candles=candles,
        structure=[{
            "index": 5, "price": 99.0, "kind": "LOW",
            "confirmation_index": 7,
        }],
        liquidity_layers={
            "swing": [{
                "price": 100.0, "touches": 2, "type": "BUY_SIDE",
                "formed_at": 1,
            }],
            "internal": [],
        },
    )

    assert result["is_sweep"] is True
    assert result["post_structure"]["confirmed"] is False


def test_sweep_confirmation_rejects_pivot_not_yet_confirmed():
    engine = LiquiditySweepEngine()
    # The sweep is present, but the post-sweep low pivot is the last candle:
    # there is no right-hand candle yet, so the mini-structure is unconfirmed.
    result = engine.detect(
        candles=_multi_candle_sweep_series()[:6],
        structure=[{
            "index": 5, "price": 99.0, "kind": "LOW",
            "confirmation_index": 10,
        }],
        liquidity_layers={
            "swing": [{
                "price": 100.0, "touches": 2, "type": "BUY_SIDE",
                "formed_at": 1,
            }],
            "internal": [],
        },
    )

    assert result["is_sweep"] is True
    assert result["post_structure"]["confirmed"] is False


def test_sweep_expires_after_confirmation_lookback_window():
    engine = LiquiditySweepEngine()
    candles = _multi_candle_sweep_series()
    candles.extend([
        _candle(9, 98.9, 99.2, 98.7, 99.0),
        _candle(10, 99.0, 99.3, 98.8, 99.1),
        _candle(11, 99.1, 99.4, 98.9, 99.2),
        _candle(12, 99.2, 99.5, 99.0, 99.3),
    ])
    result = engine.detect(
        candles=candles,
        structure=[{
            "index": 5, "price": 99.0, "kind": "LOW",
            "confirmation_index": 7,
        }],
        liquidity_layers={
            "swing": [{
                "price": 100.0, "touches": 2, "type": "BUY_SIDE",
                "formed_at": 1,
            }],
            "internal": [],
        },
    )

    assert result["is_sweep"] is False


def test_sweep_cannot_use_a_pool_formed_after_the_sweep():
    engine = LiquiditySweepEngine()
    result = engine.detect(
        candles=_multi_candle_sweep_series(),
        structure=[],
        liquidity_layers={
            "swing": [{
                "price": 100.0, "touches": 2, "type": "BUY_SIDE",
                "formed_at": 6,
            }],
            "internal": [],
        },
    )

    assert result["is_sweep"] is False



def test_sell_side_sweep_confirms_bullish_market_structure_on_a_later_close():
    engine = LiquiditySweepEngine()
    candles = [
        _candle(0, 100.3, 100.8, 100.1, 100.4),
        _candle(1, 100.4, 100.9, 100.2, 100.5),
        _candle(2, 100.5, 100.8, 100.1, 100.4),
        _candle(3, 100.4, 100.6, 99.5, 100.2),   # SSL sweep
        _candle(4, 100.2, 100.6, 100.0, 100.3),
        _candle(5, 100.6, 101.0, 100.2, 100.6),  # post-sweep swing high
        _candle(6, 100.6, 100.8, 100.4, 100.7),
        _candle(7, 100.7, 100.9, 100.5, 100.8),  # pivot confirmation
        _candle(8, 100.8, 101.3, 100.6, 101.1),  # close breaks the swing high
    ]
    result = engine.detect(
        candles=candles,
        structure=[{
            "index": 5, "price": 101.0, "kind": "HIGH", "label": "LH",
            "confirmation_index": 7,
        }],
        liquidity_layers={
            "swing": [{
                "price": 100.0, "touches": 2, "type": "SELL_SIDE",
                "liquidity_kind": "SWING", "formed_at": 1,
            }],
            "internal": [],
        },
    )

    assert result["is_sweep"] is True
    assert result["sweep_side"] == "SELL_SIDE"
    assert result["post_structure"]["confirmed"] is True
    assert result["post_structure"]["direction"] == "BULLISH"
    assert result["post_structure"]["confirmation_index"] == 8



def test_retained_buy_side_sweep_expires_when_price_closes_back_above_pool():
    engine = LiquiditySweepEngine()
    candles = _multi_candle_sweep_series()
    candles.append(_candle(9, 98.9, 100.2, 98.8, 100.1))
    result = engine.detect(
        candles=candles,
        structure=[{
            "index": 5, "price": 99.0, "kind": "LOW",
            "confirmation_index": 7,
        }],
        liquidity_layers={
            "swing": [{
                "price": 100.0, "touches": 2, "type": "BUY_SIDE",
                "formed_at": 1,
            }],
            "internal": [],
        },
    )

    assert result["is_sweep"] is False


def test_retained_sell_side_sweep_expires_when_price_closes_back_below_pool():
    engine = LiquiditySweepEngine()
    candles = [
        _candle(0, 100.3, 100.8, 100.1, 100.4),
        _candle(1, 100.4, 100.9, 100.2, 100.5),
        _candle(2, 100.5, 100.8, 100.1, 100.4),
        _candle(3, 100.4, 100.6, 99.5, 100.2),   # SSL sweep
        _candle(4, 100.2, 100.6, 100.0, 100.3),
        _candle(5, 100.6, 101.0, 100.2, 100.6),
        _candle(6, 100.6, 100.8, 100.4, 100.7),
        _candle(7, 100.7, 100.9, 100.5, 100.8),
        _candle(8, 100.8, 101.3, 100.6, 101.1),
        _candle(9, 101.1, 101.2, 99.8, 99.9),  # close back below SSL
    ]
    result = engine.detect(
        candles=candles,
        structure=[],
        liquidity_layers={
            "swing": [{
                "price": 100.0, "touches": 2, "type": "SELL_SIDE",
                "formed_at": 1,
            }],
            "internal": [],
        },
    )

    assert result["is_sweep"] is False
