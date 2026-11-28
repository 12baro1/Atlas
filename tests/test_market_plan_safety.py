"""Regression tests for the two failure modes: stale MARKET and sub-ATR stops."""
from __future__ import annotations

import logging
import time

import pytest

import opportunity_pool
from atlas_runtime import AtlasRuntime
from market_plan_safety import check_market_plan
from strategy_lab import _risk_validate_candidate
from tests.test_portfolio_ranking_and_market_tracking import candidate, publish


class FakeMarket:
    def __init__(self, *, last=100.0, high=100.2, low=99.8,
                 timestamp=None, bars=None, fail=False):
        self.last, self.high, self.low = last, high, low
        self.timestamp = timestamp
        self.bars = bars
        self.fail = fail

    def fetch_ticker(self, symbol):
        if self.fail:
            raise ConnectionError("offline")
        return {"last": self.last, "timestamp": self.timestamp}

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None):
        if self.fail:
            raise ConnectionError("offline")
        assert timeframe == "1m"
        if self.bars is not None:
            return self.bars
        return [[since, 100, self.high, self.low, self.last, 10]]


def plan(entry=100.0, stop=99.0, atr=1.0, direction="LONG"):
    return {
        "entry": entry, "stop_loss": stop, "atr": atr,
        "direction": direction, "entry_type": "MARKET",
        "tp1": 102 if direction == "LONG" else 98,
        "tp2": 104 if direction == "LONG" else 96,
        "tp3": 106 if direction == "LONG" else 94,
    }


@pytest.mark.parametrize("side,stop", [("LONG", 99.6), ("SHORT", 100.4)])
def test_final_stop_below_atr_floor_is_rejected(side, stop):
    result = _risk_validate_candidate(plan(stop=stop, direction=side))
    assert result["eligible"] is False
    assert result["reason"] == "STOP_BELOW_ATR_FLOOR"


def test_final_atr_floor_does_not_expand_structural_stop():
    item = plan(stop=99.0)
    _risk_validate_candidate(item)
    assert item["stop_loss"] == 99.0


def test_recent_long_market_rejects_stop_wick_even_after_rebound():
    now = int(time.time() * 1000)
    start = now - 20_000
    market = FakeMarket(last=100.05, low=98.9, timestamp=now)
    result = check_market_plan(market, "BTC/USDT:USDT", "LONG", 100, 99, start, now_ms=now)
    assert result == (False, "MARKET_STOP_ALREADY_HIT")


def test_recent_short_market_rejects_stop_wick_even_after_rebound():
    now = int(time.time() * 1000)
    start = now - 20_000
    market = FakeMarket(last=100.05, high=101.1, timestamp=now)
    result = check_market_plan(market, "BTC/USDT:USDT", "SHORT", 100, 101, start, now_ms=now)
    assert result == (False, "MARKET_STOP_ALREADY_HIT")


def test_recent_market_accepts_price_and_wick_on_safe_side():
    now = int(time.time() * 1000)
    start = now - 20_000
    market = FakeMarket(last=100.05, high=100.2, low=99.8, timestamp=now)
    assert check_market_plan(market, "BTC/USDT:USDT", "LONG", 100, 99, start, now_ms=now)[0]


def test_market_preflight_blocks_degraded_tp1_before_showing_it_to_user():
    now = int(time.time() * 1000)
    market = FakeMarket(last=100.25, high=100.3, low=99.8, timestamp=now)
    assert check_market_plan(
        market, "BTC/USDT:USDT", "LONG", 100, 98, now - 10_000,
        tp1=101.9, now_ms=now,
    ) == (False, "MARKET_ENTRY_QUALITY_REJECTED")


@pytest.mark.parametrize("reason,market", [
    ("MARKET_ENTRY_PRICE_STALE", FakeMarket(last=101, low=99.5)),
    ("MARKET_VERIFICATION_UNAVAILABLE", FakeMarket(fail=True)),
    ("MARKET_STOP_ALREADY_HIT", FakeMarket(last=98.8)),
])
def test_market_preflight_rejects_stale_or_unverified_prices(reason, market):
    now = int(time.time() * 1000)
    market.timestamp = now
    assert check_market_plan(market, "BTC/USDT:USDT", "LONG", 100, 99, now - 10_000, now_ms=now)[1] == reason


def test_market_signal_expires_without_network_requests():
    now = int(time.time() * 1000)
    market = FakeMarket(fail=True)
    assert check_market_plan(market, "BTC/USDT:USDT", "LONG", 100, 99, now - 130_000, now_ms=now) == (
        False, "MARKET_SIGNAL_EXPIRED"
    )


def test_current_market_uses_all_closed_minutes_since_signal():
    now = 1_800_000_135_000
    start = now - 100_000
    first_minute = start // 60_000 * 60_000
    recent_minute = now // 60_000 * 60_000
    market = FakeMarket(timestamp=now, bars=[[recent_minute, 100, 100.2, 99.8, 100, 1]])
    arguments = (market, "BTC/USDT:USDT", "LONG", 100, 99, start)
    assert check_market_plan(*arguments, now_ms=now) == (False, "MARKET_1M_HISTORY_GAP")
    market.bars.extend([stamp, 100, 100.2, 99.8, 100, 1]
                       for stamp in range(first_minute, recent_minute, 60_000))
    assert check_market_plan(*arguments, now_ms=now)[0]


def test_old_market_is_not_listed_as_new_best_opportunity(tmp_path):
    pool = opportunity_pool.OpportunityPool(base_path=str(tmp_path / "pool"), auto_persist=False)
    try:
        item = candidate("BTC", entry_type="MARKET")
        publish(pool, item)
        assert pool.get_best_setups(limit=5)
        item.created_at_ms -= 3 * 60_000
        item.evidence_at_ms = int(time.time() * 1000)
        assert pool.get_best_setups(limit=5) == []
        # History is still available until strategy-native invalidation.
        assert pool.get_setup(item.setup_id) is item
    finally:
        pool.stop()


def test_market_wick_hides_proposal_without_guessing_existing_trade_order(tmp_path, monkeypatch):
    pool = opportunity_pool.OpportunityPool(base_path=str(tmp_path / "pool"), auto_persist=False)
    try:
        item = candidate("BTC", entry_type="MARKET")
        publish(pool, item)
        pool.tracking.follow(pool_chat := "chat", [item])
        assert len(pool.tracking.tracked(pool_chat)) == 1
        assert pool.tracking.tracked(pool_chat)[0][2] == "WAITING"
        now = int(time.time() * 1000)
        market = FakeMarket(last=100.05, low=98.9, timestamp=now)
        monkeypatch.setattr("data_engine.exchange", market)
        runtime = AtlasRuntime.__new__(AtlasRuntime)
        runtime._opportunity_pool = lambda: pool
        runtime.logger = logging.getLogger("test.market.guard")
        assert runtime.verify_market_opportunity(item) is False
        assert pool.get_best_setups() == []
        tracked = pool.tracking.tracked(pool_chat)
        assert tracked[0][2] == "WAITING"
        assert not pool.tracking.pending_notifications(pool_chat)
    finally:
        pool.stop()


def test_transient_market_verification_failure_can_retry_same_fresh_setup(tmp_path, monkeypatch):
    pool = opportunity_pool.OpportunityPool(base_path=tmp_path / "pool", auto_persist=False)
    try:
        item = candidate("BTC", entry_type="MARKET")
        item.tp1, item.tp2, item.tp3 = 102.0, 104.0, 106.0
        publish(pool, item)
        market = FakeMarket(fail=True)
        monkeypatch.setattr("data_engine.exchange", market)
        runtime = AtlasRuntime.__new__(AtlasRuntime)
        runtime._opportunity_pool = lambda: pool
        runtime.logger = logging.getLogger("test.market.guard")
        assert runtime.verify_market_opportunity(item) is False
        assert pool.get_best_setups() == [item]
        market.fail = False
        market.timestamp = int(time.time() * 1000)
        assert runtime.verify_market_opportunity(item) is True
    finally:
        pool.stop()
