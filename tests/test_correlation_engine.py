"""Correlation engine regression tests for over-blocking fix."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.candle import Candle
from correlation_engine import CorrelationEngine


def _uptrend(steps=100, start=100.0, step=5.0):
    return [Candle(i, start + i * step, start + i * step, start + i * step - 1, start + i * step, 100) for i in range(steps)]


def _downtrend(steps=100, start=50000.0, step=40.0):
    return [Candle(i, start - i * step, start - i * step, start - i * step - 100, start - i * step, 0) for i in range(steps)]


def test_no_universe_does_not_block_long():
    r = CorrelationEngine().evaluate("SOL/USDT:USDT", "LONG", {})
    assert r["active"] is False
    assert r["trade_allowed"] is True


def test_bullish_btc_does_not_block_long():
    r = CorrelationEngine().evaluate("SOL/USDT:USDT", "LONG", {"correlation_universe": {"BTC": _uptrend()}})
    assert r["active"] is True
    assert r["trade_allowed"] is True


def test_strong_bearish_btc_is_entry_counterpressure_not_a_veto():
    r = CorrelationEngine().evaluate("SOL/USDT:USDT", "LONG", {"correlation_universe": {"BTC": _downtrend()}})
    assert r["trade_allowed"] is True
    assert r["counterpressure"] is True
    assert r["opposing_markets"] == ["BTC"]


def test_btc_trades_not_guarded():
    r = CorrelationEngine().evaluate("BTC/USDT:USDT", "LONG", {"correlation_universe": {"BTC": _downtrend()}})
    assert r["trade_allowed"] is True


def test_weak_noise_downtrend_does_not_block_long():
    noise = [Candle(i, 100 + (i % 3) * 0.5, 100 + (i % 3) * 0.5, 99, 100 + (i % 3) * 0.5, 100) for i in range(90)]
    r = CorrelationEngine().evaluate("SOL/USDT:USDT", "LONG", {"correlation_universe": {"BTC": noise}})
    # Zayof trend SACIDAM gelmezse ATR normalize guc kucuk -> LONG engellenmez.
    assert r["trade_allowed"] is True
def test_strong_bullish_btc_is_counterpressure_for_short_without_blocking():
    r = CorrelationEngine().evaluate("SOL/USDT:USDT", "SHORT", {"correlation_universe": {"BTC": _uptrend()}})
    assert r["trade_allowed"] is True
    assert r["counterpressure"] is True
    assert r["opposing_markets"] == ["BTC"]


def test_correlation_event_identity_uses_latest_source_candle_timestamps():
    btc = _uptrend()
    eth = _downtrend()
    btc[-1].time = 1_700_000_000_000
    eth[-1].time = 1_700_000_060_000
    result = CorrelationEngine().evaluate(
        "SOL/USDT:USDT",
        "LONG",
        {"correlation_universe": {"BTC": btc, "ETH": eth}},
    )
    assert result["event_id"] == (
        "correlation:BTC:correlation_market:1700000000000|"
        "ETH:correlation_market:1700000060000"
    )


def test_correlation_event_identity_is_optional_without_source_timestamps():
    candles = _uptrend()
    for candle in candles:
        candle.time = None
    result = CorrelationEngine().evaluate(
        "SOL/USDT:USDT",
        "LONG",
        {"correlation_universe": {"BTC": candles}},
    )
    assert result["event_id"] is None
