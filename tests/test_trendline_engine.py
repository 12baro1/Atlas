"""Test suite for the TrendlineEngine (trendline liquidity + trendline sweep)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.candle import Candle
from trendline_engine import TrendlineEngine, TrendlineSweep


def c(time, open_, high, low, close, volume=0):
    return Candle(time, open_, high, low, close, volume)


def sample_structure():
    """Rising lows -> SUPPORT trendline through lows at indices 2, 5, 8."""
    return [
        {"index": 2, "price": 100.0, "kind": "LOW", "label": "HL"},
        {"index": 5, "price": 101.5, "kind": "LOW", "label": "HL"},
        {"index": 8, "price": 103.0, "kind": "LOW", "label": "HL"},
    ]


def sample_candles():
    candles = []
    for i in range(12):
        base = 100 + i * 0.5
        candles.append(c(i, base, base + 0.3, base - 0.3, base + 0.1))
    return candles


def test_support_trendline_detected():
    engine = TrendlineEngine(min_touches=2)
    structure = sample_structure()
    candles = sample_candles()

    result = engine.detect(structure, candles, "SUPPORT")

    assert len(result) == 1
    tl = result[0]
    assert tl.direction == "SUPPORT"
    assert tl.touches >= 2
    assert tl.slope > 0  # rising support


def test_resistance_trendline_detected():
    engine = TrendlineEngine(min_touches=2)
    structure = [
        {"index": 2, "price": 110.0, "kind": "HIGH", "label": "LH"},
        {"index": 5, "price": 108.5, "kind": "HIGH", "label": "LH"},
        {"index": 8, "price": 107.0, "kind": "HIGH", "label": "LH"},
    ]
    candles = []
    for i in range(12):
        base = 105 - i * 0.5
        candles.append(c(i, base, base + 0.3, base - 0.3, base - 0.1))

    result = engine.detect(structure, candles, "RESISTANCE")

    assert len(result) == 1
    assert result[0].direction == "RESISTANCE"
    assert result[0].slope < 0  # falling resistance


def test_trendline_liquidity_payload():
    engine = TrendlineEngine(min_touches=2)
    candles = sample_candles()
    liquidity = engine.detect_liquidity(sample_structure(), candles, current_price=104.0)

    assert isinstance(liquidity, list)
    assert all(item["kind"] == "TRENDLINE" for item in liquidity)
    assert all(item["type"] in ("BUY_SIDE", "SELL_SIDE") for item in liquidity)
    assert all("distance" in item and "touches" in item for item in liquidity)


def test_trendline_sweep_detection():
    engine = TrendlineEngine(min_touches=2)
    structure = sample_structure()
    # Mum 9: düşük fiyat trendline altına iner (sweep), sonra yukarı kapanır
    candles = sample_candles()
    candles[9] = c(9, 103.5, 103.8, 102.0, 103.6)  # aşağı wick + yukarı kapanış

    sweep = engine.detect_sweep(structure, candles, current_index=9)

    assert isinstance(sweep, TrendlineSweep)
    assert sweep.active is True
    assert sweep.direction == "SELL_SIDE"
    assert sweep.wick_pierce > 0


def test_trendline_sweep_no_false_positive():
    engine = TrendlineEngine(min_touches=2)
    structure = sample_structure()
    candles = sample_candles()  # normal mumlar, sweep yok

    sweep = engine.detect_sweep(structure, candles)

    assert sweep.active is False


def test_serialize_sweep():
    engine = TrendlineEngine(min_touches=2)
    structure = sample_structure()
    candles = sample_candles()
    candles[9] = c(9, 103.5, 103.8, 102.0, 103.6)

    sweep = engine.detect_sweep(structure, candles, current_index=9)
    payload = engine.serialize(sweep, candles=candles)

    assert payload["active"] is True
    assert payload["event_id"].startswith("trendline_sweep:trendline:SUPPORT:")
    assert payload["trendline"]["direction"] == "SUPPORT"
    assert payload["direction"] == "SELL_SIDE"



def test_best_fit_cache_reuses_geometry_without_sharing_mutable_state():
    engine = TrendlineEngine(min_touches=2)
    points = [
        {"index": 2, "price": 100.0},
        {"index": 5, "price": 101.5},
        {"index": 8, "price": 103.0},
    ]
    candles = sample_candles()

    first = engine._best_fit(points, candles)[0]
    first.slope = 999.0
    second = engine._best_fit(points, candles)[0]

    assert second.slope == 0.5
    assert second.slope != first.slope
    assert len(engine._fit_cache) == 1


def test_best_fit_cache_is_bounded():
    engine = TrendlineEngine(min_touches=2)
    candles = sample_candles()

    for offset in range(engine._fit_cache_maxsize + 20):
        points = [
            {"index": 2, "price": 100.0 + offset},
            {"index": 5, "price": 101.5 + offset},
            {"index": 8, "price": 103.0 + offset},
        ]
        engine._best_fit(points, candles)

    assert len(engine._fit_cache) <= engine._fit_cache_maxsize


def test_best_fit_cache_rechecks_break_state_for_current_candles():
    engine = TrendlineEngine(min_touches=2)
    points = [
        {"index": 2, "price": 100.0},
        {"index": 5, "price": 101.5},
        {"index": 8, "price": 103.0},
    ]
    candles = sample_candles()

    first = engine._best_fit(points, candles)[0]
    assert first.broken is False

    # Same swing geometry, but the latest candle now breaks the support line.
    candles[10] = c(10, 104.0, 104.2, 103.0, 104.1)
    second = engine._best_fit(points, candles)[0]

    assert second.broken is True
    assert second.break_index == 10
