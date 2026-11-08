import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import _has_dynamic_market_context


@pytest.mark.parametrize(
    "key,value",
    [
        ("orderbook", {"bids": [[100.0, 1.0]], "asks": [[101.0, 1.0]]}),
        ("recent_trades", [{"timestamp": 1, "side": "buy", "amount": 1.0}]),
        ("open_interest", [1000.0]),
        ("funding_rate", [0.0001]),
        ("economic_events", [{"timestamp": 1, "impact": "high"}]),
        ("smt_universe", {"BTC": {"15m": [1, 2, 3]}}),
    ],
)
def test_incremental_cache_is_bypassed_for_dynamic_market_context(key, value):
    assert _has_dynamic_market_context({key: value}) is True


def test_incremental_cache_remains_available_for_candle_only_payloads():
    assert _has_dynamic_market_context({
        "symbol": "BTC/USDT:USDT",
        "orderbook": None,
        "recent_trades": None,
        "open_interest": [],
        "funding_rate": [],
    }) is False
