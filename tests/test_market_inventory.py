"""Offline tests for the Gate.io market inventory (no network access)."""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_inventory import MarketInventory, reset_market_inventory


class FakeGateExchange:
    """Deterministic stand-in for GateFuturesExchange (offline only)."""

    def __init__(self, contracts=None, fail_times=0):
        self.contracts = contracts if contracts is not None else [
            {"name": "BTC_USDT", "quanto_multiplier": "0.0001", "order_size_min": 1},
            {"name": "ETH_USDT", "quanto_multiplier": "0.01", "order_size_min": 1},
            {"name": "OLD_USDT", "quanto_multiplier": "1", "in_delisting": True},
            {"name": "SUSPENDED_USDT", "quanto_multiplier": "1", "trade_status": "suspended"},
        ]
        self.fail_times = int(fail_times)
        self.calls = 0

    def load_markets(self, reload=False, params=None):
        self.calls += 1
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("temporary Gate.io outage")
        markets = {}
        for row in self.contracts:
            if row.get("in_delisting"):
                continue
            name = row["name"]
            symbol = f"{name.split('_')[0]}/{name.split('_')[1]}:{name.split('_')[1]}"
            markets[symbol] = {
                "id": name, "symbol": symbol, "quote": "USDT", "settle": "USDT",
                "swap": True, "linear": True, "active": True, "info": dict(row),
            }
        return markets


def make_inventory(tmp_path, exchange, **kwargs):
    reset_market_inventory()
    return MarketInventory(base_path=str(tmp_path / "inv"), exchange=exchange, **kwargs)


def test_discovers_all_usdt_perpetuals_no_fixed_cap(tmp_path):
    exchange = FakeGateExchange()
    inventory = make_inventory(tmp_path, exchange)
    symbols = inventory.get_symbols()
    assert symbols == ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    # Delisted and suspended contracts excluded
    assert "OLD/USDT:USDT" not in symbols
    assert "SUSPENDED/USDT:USDT" not in symbols
    status = inventory.status()
    assert status["source"] == "gateio_usdt_perpetuals"
    assert status["symbol_count"] == 2


def test_delisted_contracts_filtered(tmp_path):
    exchange = FakeGateExchange(contracts=[{"name": "BTC_USDT"}, {"name": "DEAD_USDT", "in_delisting": True}])
    inventory = make_inventory(tmp_path, exchange)
    assert inventory.get_symbols() == ["BTC/USDT:USDT"]


def test_ttl_cache_prevents_rate_limit_abuse(tmp_path):
    exchange = FakeGateExchange()
    inventory = make_inventory(tmp_path, exchange, ttl_seconds=600)
    inventory.get_symbols()
    first_calls = exchange.calls
    inventory.get_symbols()
    inventory.get_symbols()
    assert exchange.calls == first_calls  # TTL honored, no extra API calls


def test_force_refresh_attempts_real_api_call(tmp_path):
    """force=True (user-initiated 'yenile') always attempts a real Gate.io
    refresh instead of being silently skipped by TTL. Rate-limit backoff
    still applies between retries on failure."""
    exchange = FakeGateExchange()
    inventory = make_inventory(tmp_path, exchange, ttl_seconds=600)
    inventory.get_symbols()          # first call: 1 API call
    inventory.refresh(force=True)    # explicit refresh: another real API call
    assert exchange.calls == 2


def test_refresh_without_force_respects_ttl(tmp_path):
    """Automatic (non-forced) refresh still respects the TTL."""
    exchange = FakeGateExchange()
    inventory = make_inventory(tmp_path, exchange, ttl_seconds=600)
    inventory.get_symbols()
    inventory.refresh(force=False)   # within TTL: no new API call
    assert exchange.calls == 1


def test_retry_on_temporary_failure(tmp_path):
    exchange = FakeGateExchange(fail_times=2)
    inventory = make_inventory(
        tmp_path, exchange, max_retries=3, retry_backoff_seconds=0.01
    )
    symbols = inventory.get_symbols()
    assert symbols == ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    assert exchange.calls == 3  # two failures + one success


def test_retry_exhausted_keeps_previous_snapshot(tmp_path):
    exchange = FakeGateExchange()
    inventory = make_inventory(tmp_path, exchange, ttl_seconds=600)
    first = inventory.get_symbols()
    exchange.fail_times = 99
    # Make the cache stale so a real refresh is attempted, then fail it
    inventory._last_refresh_ms = 0
    second = inventory.get_symbols()
    assert second == first  # never empties the universe on outage
    assert inventory.status()["last_error"]


def test_state_survives_restart(tmp_path):
    exchange = FakeGateExchange()
    inventory = make_inventory(tmp_path, exchange)
    inventory.get_symbols()
    snapshot_before = inventory.status()

    # Simulate restart: fresh instance restores persisted state
    reset_market_inventory()
    restored = MarketInventory(base_path=str(tmp_path / "inv"), exchange=FakeGateExchange())
    assert sorted(restored._snapshot.keys()) == ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    assert restored.status()["last_refresh_ms"] == snapshot_before["last_refresh_ms"]


def test_market_info_lookup(tmp_path):
    inventory = make_inventory(tmp_path, FakeGateExchange())
    inventory.get_symbols()
    info = inventory.market_info("BTC/USDT:USDT")
    assert info["id"] == "BTC_USDT"
    assert inventory.market_info("NOPE/USDT:USDT") is None
