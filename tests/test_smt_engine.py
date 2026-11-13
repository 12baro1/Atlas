import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.candle import Candle
from smt_engine import SMTDivergenceEngine


def _candles_from_prices(prices):
    candles = []
    base_time = 1_700_000_000_000

    for index, price in enumerate(prices):
        candles.append(
            Candle(
                time=base_time + (index * 60_000),
                open=price - 0.2,
                high=price + 0.5,
                low=price - 0.5,
                close=price + 0.2,
                volume=100.0,
            )
        )

    return candles


def test_detects_bearish_smt_divergence():
    engine = SMTDivergenceEngine()

    primary = _candles_from_prices([10, 13, 11, 15, 12, 17, 13, 19, 14, 21, 15])
    compare = _candles_from_prices([10, 13, 11, 14, 12, 13.8, 12.5, 13.5, 12.8, 13.2, 12.9])

    result = engine.detect(
        primary_symbol="SOL/USDT:USDT",
        primary_timeframes={"15m": primary},
        smt_universe={
            "BTC/USDT:USDT": {"15m": compare},
            "SOL/USDT:USDT": {"15m": primary},
        },
        selected_symbols=["SOL/USDT:USDT"],
        timeframes=["15m"],
        pivot_left=1,
        pivot_right=1,
    )

    assert result["active"] is True
    assert result["bearish"]
    assert result["best"]["type"] == "BEARISH"
    assert result["best"]["event_id"].startswith("15m:smt:SOL/USDT:USDT:BTC/USDT:USDT:BEARISH:")
    assert 0 <= result["best"]["confidence"] <= 100


def test_detects_bullish_smt_divergence():
    engine = SMTDivergenceEngine()

    primary = _candles_from_prices([20, 18, 19, 16, 18, 14, 17, 12, 16, 10, 15])
    compare = _candles_from_prices([20, 18, 19, 16, 18, 16.2, 17.5, 16.5, 17, 16.8, 16.9])

    result = engine.detect(
        primary_symbol="ETH/USDT:USDT",
        primary_timeframes={"4h": primary},
        smt_universe={
            "BTC/USDT:USDT": {"4h": compare},
            "ETH/USDT:USDT": {"4h": primary},
        },
        timeframes=["4h"],
        pivot_left=1,
        pivot_right=1,
    )

    assert result["active"] is True
    assert result["bullish"]
    assert result["best"]["type"] == "BULLISH"
    assert result["best"]["event_id"].startswith("4h:smt:ETH/USDT:USDT:BTC/USDT:USDT:BULLISH:")
    assert 0 <= result["best"]["confidence"] <= 100


def test_uses_only_confirmed_pivots_non_repaint():
    engine = SMTDivergenceEngine()

    prices = [10, 14, 11, 15, 12, 16, 13]
    candles = _candles_from_prices(prices)

    pivots = engine._confirmed_pivots(candles, left=1, right=2)
    last_allowed_index = len(candles) - 3

    assert all(item["index"] <= last_allowed_index for item in pivots["highs"])
    assert all(item["index"] <= last_allowed_index for item in pivots["lows"])


def test_pivot_alignment_uses_timestamp_not_different_array_offsets():
    engine = SMTDivergenceEngine()
    primary = {"index": 900, "time": 1_700_000_000_000, "price": 100.0}
    comparison = {"index": 120, "time": 1_700_000_000_000 + 5 * 60_000, "price": 2.0}
    assert engine._aligned(primary, comparison, 1, "15m") is True


def test_smt_alignment_rejects_pivots_far_apart_in_time():
    engine = SMTDivergenceEngine()
    primary = {"index": 100, "time": 1_700_000_000_000, "price": 100.0}
    comparison = {"index": 101, "time": 1_700_000_000_000 + 10 * 15 * 60_000, "price": 2.0}
    assert engine._aligned(primary, comparison, 2, "15m") is False


def test_smt_confidence_is_independent_of_price_scale():
    engine = SMTDivergenceEngine()
    args = {
        "timeframe": "4h",
        "primary_prev": {"index": 1, "price": 100.0},
        "primary_last": {"index": 2, "price": 110.0},
        "compare_prev": {"index": 1, "price": 2.0},
        "compare_last": {"index": 2, "price": 2.1},
        "bullish": False,
    }
    first = engine._confidence_score(**args)
    args["primary_prev"] = {"index": 1, "price": 10_000.0}
    args["primary_last"] = {"index": 2, "price": 11_000.0}
    args["compare_prev"] = {"index": 1, "price": 200.0}
    args["compare_last"] = {"index": 2, "price": 210.0}
    assert engine._confidence_score(**args) == first
