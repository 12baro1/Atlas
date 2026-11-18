"""Regression tests for PR #173 hardening: runtime setup conversion and pool integrity.

All tests are offline and deterministic; no exchange, Telegram or network access.
"""
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from atlas_runtime import AtlasRuntime
from opportunity_pool import (
    OpportunityPool,
    SetupCandidate,
    SetupStatus,
    SetupType,
    reset_opportunity_pool,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_runtime():
    """Bypass the heavy AtlasRuntime.__init__ (no engine, no exchange)."""
    return AtlasRuntime.__new__(AtlasRuntime)


def make_selected(
    direction="LONG",
    entry=50000.0,
    stop=49500.0,
    entry_type="LIMIT",
    strategy_id="smc",
    strategy="SMC (bütünleşik uzman motorları)",
    estimated_net_rr=2.4,
    partial_weights=None,
):
    return {
        "strategy_id": strategy_id,
        "strategy": strategy,
        "direction": direction,
        "entry_type": entry_type,
        "entry": entry,
        "stop_loss": stop,
        "tp1": 51000.0,
        "tp2": 52000.0,
        "tp3": 53000.0,
        "rr_tp1": 2.0,
        "rr_tp2": 4.0,
        "rr_tp3": 6.0,
        "strength": 85.0,
        "partial_exit_weights": partial_weights or {"tp1": 0.5, "tp2": 0.3, "tp3": 0.2},
        "estimated_net_rr": estimated_net_rr,
        "reasons": ["structure confirmed"],
        "supporting_event_ids": ["ev1"],
        "opposing_event_ids": [],
    }


def make_pool(tmp_path, **kwargs):
    params = {
        "base_path": str(tmp_path / "pool"),
        "auto_persist": False,
        "max_candidates": 50,
        "max_validated": 20,
        "max_history": 100,
        "expiry_hours": 48,
    }
    params.update(kwargs)
    return OpportunityPool(**params)


def test_daily_archive_preserves_live_candidate(tmp_path):
    pool = make_pool(tmp_path)
    pool.add_candidate(make_candidate("keep"))
    pool.archive_and_reset_scan_pools("2026-11-18")
    pool.stop()
    reopened = make_pool(tmp_path)
    assert [c.setup_id for c in reopened.get_all_setups()["candidates"]] == ["keep"]
    reopened.stop()


def make_candidate(sid, sym="BTC/USDT:USDT", strat="smc", entry_type="LIMIT"):
    return SetupCandidate(
        setup_id=sid,
        symbol=sym,
        strategy_id=strat,
        strategy_name=strat,
        direction="LONG",
        entry_type=entry_type,
        entry_price=50000.0,
        stop_loss=49500.0,
        tp1=51000.0,
        tp2=52000.0,
        tp3=53000.0,
        rr_tp1=2.0,
        rr_tp2=4.0,
        rr_tp3=6.0,
        net_rr=3.5,
        risk_reward=3.5,
        confidence=85.0,
        grade="A+",
        score=85.0,
        net_rr_after_costs=3.2,
        status=SetupStatus.DISCOVERED.value,
        setup_type=SetupType.LIMIT.value if entry_type == "LIMIT" else SetupType.MARKET.value,
        regime="TREND",
        market_phase="Expansion",
        created_at_ms=int(time.time() * 1000),
        validated_at_ms=0,
    )


# ---------------------------------------------------------------------------
# _setup_to_candidate: RR geometry and validation
# ---------------------------------------------------------------------------

def test_rr_reward_measured_from_entry_not_stop():
    runtime = make_runtime()
    candidate = runtime._setup_to_candidate(make_selected(), "BTC/USDT:USDT")
    assert candidate is not None
    # risk = |entry - SL| = 500; reward from ENTRY: |tp1-entry| = 1000 -> rr 2.0
    assert candidate.rr_tp1 == pytest.approx(2.0)
    assert candidate.rr_tp2 == pytest.approx(4.0)
    assert candidate.rr_tp3 == pytest.approx(6.0)


def test_short_direction_rr_and_ordering():
    runtime = make_runtime()
    selected = make_selected(direction="SHORT", entry=50000.0, stop=50500.0)
    selected.update({"tp1": 49000.0, "tp2": 48000.0, "tp3": 47000.0})
    candidate = runtime._setup_to_candidate(selected, "BTC/USDT:USDT")
    assert candidate is not None
    assert candidate.direction == "SHORT"
    assert candidate.rr_tp1 == pytest.approx(2.0)
    assert candidate.rr_tp3 == pytest.approx(6.0)


def test_long_tp_ordering_violation_rejected():
    runtime = make_runtime()
    selected = make_selected()
    selected["tp2"] = 50500.0  # tp1 < tp2 violated (tp2 between entry and tp1)
    assert runtime._setup_to_candidate(selected, "BTC/USDT:USDT") is None


def test_short_stop_below_entry_rejected():
    runtime = make_runtime()
    selected = make_selected(direction="SHORT", entry=50000.0, stop=49000.0)
    assert runtime._setup_to_candidate(selected, "BTC/USDT:USDT") is None


def test_missing_tp_rejected():
    runtime = make_runtime()
    selected = make_selected()
    selected["tp3"] = None
    assert runtime._setup_to_candidate(selected, "BTC/USDT:USDT") is None


def test_invalid_direction_rejected():
    runtime = make_runtime()
    selected = make_selected(direction="SIDEWAYS")
    assert runtime._setup_to_candidate(selected, "BTC/USDT:USDT") is None


def test_non_finite_and_bad_types_rejected():
    runtime = make_runtime()
    for bad in ("not-a-number", float("nan"), float("inf"), None):
        selected = make_selected()
        selected["entry"] = bad
        assert runtime._setup_to_candidate(selected, "BTC/USDT:USDT") is None


def test_setup_type_preserves_real_market_or_limit():
    runtime = make_runtime()
    market = runtime._setup_to_candidate(make_selected(entry_type="MARKET"), "BTC/USDT:USDT")
    assert market.setup_type == SetupType.MARKET.value
    assert market.entry_type == "MARKET"
    limit = runtime._setup_to_candidate(make_selected(entry_type="LIMIT"), "BTC/USDT:USDT")
    assert limit.setup_type == SetupType.LIMIT.value
    assert limit.entry_type == "LIMIT"
    # Unknown entry type must not silently default to MARKET
    bogus = runtime._setup_to_candidate(make_selected(entry_type="TRAIL"), "BTC/USDT:USDT")
    assert bogus is None


def test_net_rr_after_costs_comes_from_risk_engine_value():
    runtime = make_runtime()
    candidate = runtime._setup_to_candidate(make_selected(estimated_net_rr=1.7), "BTC/USDT:USDT")
    assert candidate.net_rr_after_costs == pytest.approx(1.7)
    assert candidate.net_rr == pytest.approx(1.7)


def test_strategy_identity_preserved_and_deterministic_id():
    runtime = make_runtime()
    first = runtime._setup_to_candidate(
        make_selected(strategy_id="orderflow_momentum", strategy="Order Flow Momentum"),
        "ETH/USDT:USDT",
    )
    second = runtime._setup_to_candidate(
        make_selected(strategy_id="orderflow_momentum", strategy="Order Flow Momentum"),
        "ETH/USDT:USDT",
    )
    assert first.strategy_id == "orderflow_momentum"
    assert first.strategy_name == "Order Flow Momentum"
    # Deterministic id: unchanged geometry produces the same id across scans
    assert first.setup_id == second.setup_id
    # Changed geometry produces a different id
    third = runtime._setup_to_candidate(
        make_selected(strategy_id="orderflow_momentum", strategy="Order Flow Momentum", entry=50100.0),
        "ETH/USDT:USDT",
    )
    assert third.setup_id != first.setup_id


def test_confidence_from_strength_not_invented():
    runtime = make_runtime()
    candidate = runtime._setup_to_candidate(make_selected(), "BTC/USDT:USDT")
    assert candidate.confidence == pytest.approx(85.0)
    assert candidate.score == pytest.approx(85.0)


def test_trace_id_regime_phase_carried_through():
    runtime = make_runtime()
    candidate = runtime._setup_to_candidate(
        make_selected(), "BTC/USDT:USDT", trace_id="trace-1", regime="RANGE", market_phase="Distribution"
    )
    assert candidate.trace_id == "trace-1"
    assert candidate.regime == "RANGE"
    assert candidate.market_phase == "Distribution"


# ---------------------------------------------------------------------------
# Opportunity pool: persistence, eviction, lifecycle integrity
# ---------------------------------------------------------------------------

def test_auto_persist_false_starts_no_thread(tmp_path):
    pool = make_pool(tmp_path)
    assert pool._persist_thread is None
    pool.stop()


def test_auto_persist_true_starts_thread_with_interval(tmp_path):
    pool = make_pool(tmp_path, auto_persist=True, persist_interval=1)
    assert pool._persist_thread is not None
    assert pool.persist_interval == 1
    pool.stop()


def test_capacity_eviction_archives_instead_of_deleting(tmp_path):
    pool = make_pool(tmp_path, max_candidates=2)
    pool.add_candidate(make_candidate("c1", "BTC/USDT:USDT"))
    pool.add_candidate(make_candidate("c2", "ETH/USDT:USDT"))
    pool.add_candidate(make_candidate("c3", "XRP/USDT:USDT"))
    assert len(pool._candidates) == 2
    archived = pool.get_recent_history(limit=10)
    assert any(
        item.get("invalidation_reason") == "EVICTED_CAPACITY" for item in archived
    )
    pool.stop()


def test_validated_capacity_eviction_archives(tmp_path):
    pool = make_pool(tmp_path, max_candidates=10, max_validated=1)
    pool.add_candidate(make_candidate("c1", "BTC/USDT:USDT"))
    pool.validate_candidate("c1")
    pool.add_candidate(make_candidate("c2", "ETH/USDT:USDT"))
    pool.validate_candidate("c2")
    assert len(pool._validated) == 1
    assert any(
        item.get("invalidation_reason") == "EVICTED_CAPACITY"
        for item in pool.get_recent_history(limit=10)
    )
    pool.stop()


def test_zero_capacity_does_not_crash(tmp_path):
    pool = make_pool(tmp_path, max_candidates=0)
    pool.add_candidate(make_candidate("c1"))
    pool.stop()


def test_created_at_not_rewritten_on_add(tmp_path):
    pool = make_pool(tmp_path)
    candidate = make_candidate("c1")
    candidate.created_at_ms = 1700000000000
    pool.add_candidate(candidate)
    assert candidate.created_at_ms == 1700000000000
    assert candidate.expires_at_ms == 1700000000000 + 48 * 3600 * 1000
    pool.stop()


def test_fill_does_not_mutate_entry_type(tmp_path):
    pool = make_pool(tmp_path)
    pool.add_candidate(make_candidate("c1"))
    pool.validate_candidate("c1")
    assert pool.accept_setup("c1", "user1")
    assert pool.update_active_setup("c1", status=SetupStatus.ENTERED.value, entry_filled_price=50010.0)
    active = pool.get_setup("c1")
    assert active.entry_type == "LIMIT"
    assert active.entry_filled_price == 50010.0
    active.expires_at_ms = 1
    assert pool.cleanup_expired()["active"] == 0
    assert pool.get_setup("c1") is active
    pool.stop()


def test_terminal_status_archives_and_leaves_active_pool(tmp_path):
    pool = make_pool(tmp_path)
    pool.add_candidate(make_candidate("c1"))
    pool.validate_candidate("c1")
    pool.accept_setup("c1", "user1")
    pool.update_active_setup("c1", status=SetupStatus.INVALIDATED.value)
    assert pool.get_setup("c1") is None
    assert any(
        item.get("status") == SetupStatus.INVALIDATED.value
        for item in pool.get_recent_history(limit=10)
    )
    pool.stop()


def test_close_active_setup_validates_reason_and_records_price(tmp_path):
    pool = make_pool(tmp_path)
    pool.add_candidate(make_candidate("c1"))
    pool.validate_candidate("c1")
    pool.accept_setup("c1", "user1")
    assert pool.close_active_setup("c1", "TOTALLY_BOGUS", 50000.0) is False
    assert pool.get_setup("c1") is not None
    assert pool.close_active_setup("c1", "TP3", 51000.0) is True
    record = pool.get_recent_history(limit=1)[0]
    assert record["status"] == "TP3"
    assert record["close_price"] == pytest.approx(51000.0)
    pool.stop()


def test_from_dict_drops_malformed_records(tmp_path):
    assert SetupCandidate.from_dict(
        {"setup_id": "x", "symbol": "BTC/USDT:USDT", "direction": "LONG", "entry_price": "bad"}
    ) is None
    assert SetupCandidate.from_dict(
        {"setup_id": "  ", "symbol": "BTC/USDT:USDT", "direction": "LONG"}
    ) is None
    # Type coercion of string-encoded numbers must still work on a complete record
    complete = make_candidate("x")
    record = SetupCandidate.from_dict({**complete.to_dict(), "entry_price": "50000.5"})
    assert record is not None
    assert record.entry_price == pytest.approx(50000.5)
    # Incomplete records are dropped, never fabricated
    assert SetupCandidate.from_dict(
        {"setup_id": "y", "symbol": "BTC/USDT:USDT", "direction": "LONG"}
    ) is None


def test_corrupted_sqlite_store_recovers(tmp_path):
    pool = make_pool(tmp_path)
    pool.add_candidate(make_candidate("c1", "BTC/USDT:USDT"))
    pool.stop()
    # Corrupt the primary store; the pool must quarantine it and keep working.
    # The JSON mirror is then used for migration, so no data is lost.
    db_file = tmp_path / "pool" / "pool_state.db"
    db_file.write_bytes(b"this is not a sqlite database at all")
    reloaded = make_pool(tmp_path)
    assert "c1" in reloaded._candidates  # recovered via JSON migration
    quarantined = list((tmp_path / "pool").glob("pool_state.corrupt-*"))
    assert quarantined, "corrupt file must be kept for forensics"
    reloaded.stop()
    # After recovery the new state persists in the fresh store
    third = make_pool(tmp_path)
    assert "c1" in third._candidates
    third.stop()


def test_corrupted_json_mirror_ignored_sqlite_wins(tmp_path):
    pool = make_pool(tmp_path)
    pool.add_candidate(make_candidate("c1", "BTC/USDT:USDT"))
    pool.stop()
    candidates_file = tmp_path / "pool" / "candidates.json"
    candidates_file.write_text('{"version":1,"candidates":{"c1":{"setup_id":"c1","entry_price":"junk"}}}')
    reloaded = make_pool(tmp_path)
    # SQLite is the primary store: the valid record survives the broken mirror
    assert "c1" in reloaded._candidates
    reloaded.stop()


def test_restart_reloads_all_states(tmp_path):
    pool = make_pool(tmp_path)
    pool.add_candidate(make_candidate("c1", "BTC/USDT:USDT", "smc"))
    pool.add_candidate(make_candidate("c2", "ETH/USDT:USDT", "smc"))
    pool.validate_candidate("c2")
    pool.add_candidate(make_candidate("c3", "XRP/USDT:USDT", "smc"))
    pool.validate_candidate("c3")
    pool.accept_setup("c3", "user1")
    pool.stop()

    reloaded = make_pool(tmp_path)
    assert "c1" in reloaded._candidates
    assert "c2" in reloaded._validated
    assert "c3" in reloaded._active
    assert reloaded.get_setup("c3").user_id == "user1"
    reloaded.stop()


def test_add_candidate_persists_immediately_without_background_thread(tmp_path):
    """Requirement E: setup eklendiginde 30 saniyelik persist araligina
    baglanmadan SQLite'a anlik yazilmalidir (crash'te veri kaybı yok)."""
    pool = make_pool(tmp_path, auto_persist=False)
    pool.add_candidate(make_candidate("c1", "BTC/USDT:USDT", "smc"))

    # A fresh pool instance over the same SQLite store must see the candidate
    # immediately - no background persist thread was running.
    reloaded = make_pool(tmp_path, auto_persist=False)
    assert "c1" in reloaded._candidates
    assert reloaded._candidates["c1"].symbol == "BTC/USDT:USDT"
    assert reloaded._candidates["c1"].strategy_id == "smc"
    pool.stop()
    reloaded.stop()


def test_new_strategy_analysis_replaces_previous_pending_symbol_setup(tmp_path):
    pool = make_pool(tmp_path)
    old = make_candidate("c1", strat="smc")
    pool.add_candidate(old)
    pool.validate_candidate("c1")

    new = make_candidate("c2", strat="smc")
    new.direction = "SHORT"
    assert pool.add_candidate(new) is True
    assert pool.validate_candidate("c2") is True

    assert list(pool._validated) == ["c2"]
    history = pool.get_recent_history(limit=10)
    replaced = next(item for item in history if item.get("setup_id") == "c1")
    assert replaced["status"] == SetupStatus.INVALIDATED.value
    assert replaced["invalidation_reason"] == "REPLACED_BY_NEW_ANALYSIS"
    pool.stop()


def test_same_setup_identity_refreshes_without_duplicate(tmp_path):
    pool = make_pool(tmp_path)
    first = make_candidate("same")
    pool.add_candidate(first)
    pool.validate_candidate("same")

    refreshed = make_candidate("same")
    refreshed.entry_price = 50100.0
    assert pool.add_candidate(refreshed) is False
    assert list(pool._validated) == ["same"]
    assert pool._validated["same"].entry_price == pytest.approx(50100.0)
    pool.stop()


def test_new_analysis_does_not_replace_user_accepted_trade(tmp_path):
    pool = make_pool(tmp_path)
    pool.add_candidate(make_candidate("active-old"))
    pool.validate_candidate("active-old")
    assert pool.accept_setup("active-old", "user1")

    replacement = make_candidate("pending-new", strat="orderflow_momentum")
    assert pool.add_candidate(replacement) is True
    assert pool.get_setup("active-old") is not None
    assert pool.get_setup("pending-new") is not None
    pool.stop()


def test_index_pruning_keeps_maps_bounded(tmp_path):
    pool = make_pool(tmp_path)
    pool.add_candidate(make_candidate("c1", "BTC/USDT:USDT", "smc"))
    pool.reject_candidate("c1", "test rejection")
    assert "BTC/USDT:USDT" not in pool._by_symbol
    assert "smc" not in pool._by_strategy
    assert SetupStatus.DISCOVERED.value not in pool._by_status
    pool.stop()


# ---------------------------------------------------------------------------
# Pool freshness / best-5/10 filtering
# ---------------------------------------------------------------------------

def _make_validated_candidate(pool, sid, sym="BTC/USDT:USDT", strat="smc",
                              net_rr=3.2, now_ms=None, age_hours=0,
                              updated_age_hours=0, expired=False):
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    c = SetupCandidate(
        setup_id=sid, symbol=sym, strategy_id=strat, strategy_name=strat,
        direction="LONG", entry_type="LIMIT", entry_price=50000.0,
        stop_loss=49500.0, tp1=51000.0, tp2=52000.0, tp3=53000.0,
        rr_tp1=2.0, rr_tp2=4.0, rr_tp3=6.0, net_rr=net_rr,
        risk_reward=net_rr, confidence=85.0, grade="A+", score=85.0,
        net_rr_after_costs=net_rr, status=SetupStatus.VALIDATED.value,
        setup_type=SetupType.LIMIT.value, regime="TREND", market_phase="Expansion",
        created_at_ms=now_ms - int(age_hours * 3600_000),
        updated_at_ms=now_ms - int(updated_age_hours * 3600_000),
        validated_at_ms=now_ms - int(age_hours * 3600_000),
    )
    if expired:
        c.expires_at_ms = now_ms - 3600_000  # already expired
    else:
        c.expires_at_ms = now_ms + pool.expiry_hours * 3600_000
    pool._validated[sid] = c
    pool._index_candidate(c)
    return c


def test_best_setups_keeps_setup_past_expiry_timestamp_until_structure_breaks(tmp_path):
    """Setup yaşı/expiry zamanı tek başına strateji yapısını geçersiz kılmaz."""
    pool = make_pool(tmp_path, expiry_hours=24)
    now_ms = int(time.time() * 1000)
    _make_validated_candidate(pool, "good", net_rr=3.2, now_ms=now_ms)
    _make_validated_candidate(pool, "old", net_rr=5.0, now_ms=now_ms, expired=True)

    best = pool.get_best_setups(limit=5)
    symbols = {c.setup_id for c in best}
    assert "good" in symbols
    assert "old" in symbols
    assert "old" in pool._validated
    pool.stop()


def test_best_setups_keeps_old_updated_at_when_rr_and_structure_are_valid(tmp_path):
    pool = make_pool(tmp_path, expiry_hours=24)
    now_ms = int(time.time() * 1000)
    _make_validated_candidate(pool, "fresh", net_rr=3.2, now_ms=now_ms,
                              updated_age_hours=1)
    _make_validated_candidate(pool, "old", net_rr=5.0, now_ms=now_ms,
                              updated_age_hours=100)

    symbols = {c.setup_id for c in pool.get_best_setups(limit=5)}
    assert "fresh" in symbols
    assert "old" in symbols
    pool.stop()


def test_best_setups_keeps_six_hour_setup_until_strategy_reports_break(tmp_path):
    pool = make_pool(tmp_path, freshness_hours=2)
    old = make_candidate("six-hours-old")
    old.created_at_ms = int(time.time() * 1000) - 6 * 60 * 60 * 1000
    old.updated_at_ms = old.created_at_ms
    pool.add_candidate(old)
    assert pool.validate_candidate(old.setup_id) is True

    assert [item.setup_id for item in pool.get_best_setups(limit=10)] == [old.setup_id]
    assert old.setup_id in pool._validated
    pool.stop()


def test_best_setups_keeps_fresh_validated_setup(tmp_path):
    pool = make_pool(tmp_path, freshness_hours=2)
    fresh = make_candidate("fresh")
    pool.add_candidate(fresh)
    assert pool.validate_candidate(fresh.setup_id) is True

    assert [item.setup_id for item in pool.get_best_setups(limit=10)] == ["fresh"]
    pool.stop()


def test_best_setups_excludes_invalid_rr(tmp_path):
    """net_rr_after_costs 0, negatif veya olmayan setup'lar dışlanmalı."""
    pool = make_pool(tmp_path, expiry_hours=24)
    now_ms = int(time.time() * 1000)
    _make_validated_candidate(pool, "valid", net_rr=3.2, now_ms=now_ms)
    _make_validated_candidate(pool, "zero_rr", net_rr=0.0, now_ms=now_ms)
    _make_validated_candidate(pool, "neg_rr", net_rr=-1.0, now_ms=now_ms)

    best = pool.get_best_setups(limit=5)
    symbols = {c.setup_id for c in best}
    assert "valid" in symbols
    assert "zero_rr" not in symbols
    assert "neg_rr" not in symbols
    pool.stop()


def test_best_setups_keeps_missing_timestamps_when_setup_geometry_is_valid(tmp_path):
    """Timestamps are audit metadata, not strategy-structure validity."""
    pool = make_pool(tmp_path, expiry_hours=24)
    now_ms = int(time.time() * 1000)

    c = SetupCandidate(
        setup_id="no_created", symbol="BTC/USDT:USDT", strategy_id="smc",
        strategy_name="smc", direction="LONG", entry_type="LIMIT",
        entry_price=50000.0, stop_loss=49500.0, tp1=51000.0, tp2=52000.0,
        tp3=53000.0, rr_tp1=2.0, rr_tp2=4.0, rr_tp3=6.0, net_rr=3.2,
        risk_reward=3.2, confidence=85.0, grade="A+", score=85.0,
        net_rr_after_costs=3.2, status=SetupStatus.VALIDATED.value,
        setup_type=SetupType.LIMIT.value, regime="TREND", market_phase="Expansion",
        created_at_ms=0, updated_at_ms=0, validated_at_ms=0,
        expires_at_ms=now_ms + pool.expiry_hours * 3600_000,
    )
    pool._validated["no_created"] = c
    pool._index_candidate(c)

    _make_validated_candidate(pool, "valid", net_rr=3.2, now_ms=now_ms)

    best = pool.get_best_setups(limit=5)
    symbols = {c.setup_id for c in best}
    assert "valid" in symbols
    assert "no_created" in symbols
    pool.stop()


def test_strategy_structure_failure_removes_only_matching_strategy(tmp_path):
    pool = make_pool(tmp_path)
    smc = make_candidate("smc-live", "BTC/USDT:USDT", "smc")
    orderflow = make_candidate("of-live", "BTC/USDT:USDT", "orderflow_momentum")
    pool.add_candidate(smc)
    pool.validate_candidate(smc.setup_id)
    pool.add_candidate(orderflow)
    pool.validate_candidate(orderflow.setup_id)

    removed = pool.invalidate_strategy_setup(
        "BTC/USDT:USDT", "smc", "STRATEGY_STRUCTURE_BROKEN"
    )
    assert [item.setup_id for item in removed] == ["smc-live"]
    assert "smc-live" not in pool._validated
    assert "of-live" in pool._validated
    history = pool.get_recent_history(limit=10)
    archived = next(item for item in history if item["setup_id"] == "smc-live")
    assert archived["status"] == SetupStatus.INVALIDATED.value
    assert archived["invalidation_reason"] == "STRATEGY_STRUCTURE_BROKEN"
    pool.stop()


def test_strategy_structure_failure_removes_unentered_active_but_preserves_entered(tmp_path):
    pool = make_pool(tmp_path)
    pool.add_candidate(make_candidate("accepted", strat="smc"))
    pool.validate_candidate("accepted")
    assert pool.accept_setup("accepted", "user1")

    pool.add_candidate(make_candidate("entered", sym="ETH/USDT:USDT", strat="smc"))
    pool.validate_candidate("entered")
    assert pool.accept_setup("entered", "user1")
    assert pool.update_active_setup("entered", status=SetupStatus.ENTERED.value)

    removed = pool.invalidate_strategy_setup(
        "BTC/USDT:USDT", "smc", "STRATEGY_STRUCTURE_BROKEN"
    )

    assert [item.setup_id for item in removed] == ["accepted"]
    assert pool.get_setup("accepted") is None
    assert pool.get_setup("entered") is not None
    assert pool.get_setup("entered").status == SetupStatus.ENTERED.value
    archived = pool.get_recent_history(limit=1)[0]
    assert archived["setup_id"] == "accepted"
    assert archived["invalidation_reason"] == "STRATEGY_STRUCTURE_BROKEN"
    pool.stop()

def test_best_setups_only_reads_validated_pool(tmp_path):
    """en iyi 5/10 sadece doğrulanmış havuzu okur; kuyruk/havuzu değiştirmez."""
    pool = make_pool(tmp_path, auto_persist=False)
    now_ms = int(time.time() * 1000)
    _make_validated_candidate(pool, "v1", net_rr=3.2, now_ms=now_ms)

    stats_before = pool.get_stats()
    best = pool.get_best_setups(limit=5)
    stats_after = pool.get_stats()

    assert len(best) == 1
    assert best[0].setup_id == "v1"
    # Read-only: stats unchanged
    assert stats_before == stats_after
    pool.stop()
