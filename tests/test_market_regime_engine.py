import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.candle import Candle
from market_regime_engine import MarketRegimeEngine


def _candles(closes, spread=1.0):
    rows = []
    for index, close in enumerate(closes):
        open_price = close - 0.1
        rows.append(
            Candle(
                time=index * 4 * 60 * 60 * 1000,
                open=open_price,
                high=max(open_price, close) + spread,
                low=min(open_price, close) - spread,
                close=close,
                volume=100.0,
            )
        )
    return rows


def test_market_regime_detects_uptrend():
    closes = [100 + index * 1.5 + math.sin(index) * 0.15 for index in range(80)]
    result = MarketRegimeEngine().analyze(_candles(closes))
    assert result["active"] is True
    assert result["regime"] == "TRENDING_UP"
    assert result["directional_bias"] == "BULLISH"
    assert result["source"] == "bybit_ohlcv"
    assert result["event_id"].startswith("market_regime:4h:")


def test_market_regime_detects_range():
    closes = [100 + math.sin(index * 1.7) * 0.5 for index in range(80)]
    result = MarketRegimeEngine().analyze(_candles(closes, spread=0.7))
    assert result["active"] is True
    assert result["regime"] == "RANGING"
    assert result["directional_bias"] == "NEUTRAL"


def test_market_regime_requires_sufficient_history():
    result = MarketRegimeEngine().analyze(_candles([100 + index for index in range(20)]))
    assert result["active"] is False
    assert result["regime"] == "UNKNOWN"


def test_market_regime_rejects_malformed_ohlc():
    candles = _candles([100 + index for index in range(60)])
    candles[-1].high = candles[-1].low - 1
    result = MarketRegimeEngine().analyze(candles)
    assert result["active"] is False
    assert result["regime"] == "UNKNOWN"


def test_market_regime_rejects_nan_ohlcv():
    candles = _candles([100 + index for index in range(60)])
    candles[-1].close = float("nan")
    result = MarketRegimeEngine().analyze(candles)
    assert result["active"] is False
    assert result["regime"] == "UNKNOWN"


from decision_engine import DecisionEngine


def test_market_regime_alignment_changes_decision_score():
    engine = DecisionEngine()
    adjustments = []
    engine._apply_market_regime_adjustment(
        adjustments,
        {"active": True, "regime": "TRENDING_UP", "directional_bias": "BULLISH"},
        "LONG",
    )
    assert adjustments == [{"delta": 4, "label": "Market Regime aligned: TRENDING_UP"}]


def test_opposing_market_regime_penalizes_decision_score():
    engine = DecisionEngine()
    adjustments = []
    engine._apply_market_regime_adjustment(
        adjustments,
        {"active": True, "regime": "TRENDING_UP", "directional_bias": "BULLISH"},
        "SHORT",
    )
    assert adjustments == [{"delta": -8, "label": "Market Regime opposing: TRENDING_UP"}]


def test_unavailable_market_regime_does_not_change_score():
    engine = DecisionEngine()
    adjustments = []
    engine._apply_market_regime_adjustment(
        adjustments,
        {"active": False, "regime": "UNKNOWN"},
        "LONG",
    )
    assert adjustments == []


def test_phase_and_regime_same_trend_are_not_scored_twice():
    engine = DecisionEngine()
    assert engine._regime_is_represented_by_phase(
        {"phase": "Expansion", "trend": "BULLISH"},
        {"active": True, "regime": "TRENDING_UP", "directional_bias": "BULLISH"},
    ) is True


def test_phase_and_regime_directional_conflict_remains_visible():
    engine = DecisionEngine()
    assert engine._regime_is_represented_by_phase(
        {"phase": "Expansion", "trend": "BULLISH"},
        {"active": True, "regime": "TRENDING_DOWN", "directional_bias": "BEARISH"},
    ) is False


def test_ranging_phase_and_compression_regime_are_not_double_penalized():
    engine = DecisionEngine()
    assert engine._regime_is_represented_by_phase(
        {"phase": "Consolidation", "trend": "RANGE"},
        {"active": True, "regime": "COMPRESSION", "directional_bias": "NEUTRAL"},
    ) is True
