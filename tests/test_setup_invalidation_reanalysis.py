"""Regression tests for invalidated setup removal and re-analysis eligibility."""
import time
from types import SimpleNamespace

from opportunity_pool import OpportunityPool, SetupCandidate, SetupStatus, SetupType
from state_engine import StateEngine
from atlas_runtime import AtlasRuntime


def candidate(setup_id="same-setup"):
    now = int(time.time() * 1000)
    return SetupCandidate(
        setup_id=setup_id, symbol="BTC/USDT:USDT", strategy_id="smc",
        strategy_name="SMC", direction="LONG", entry_type="LIMIT",
        entry_price=100.0, stop_loss=98.0, tp1=102.0, tp2=104.0, tp3=106.0,
        rr_tp1=1.0, rr_tp2=2.0, rr_tp3=3.0, net_rr=2.0,
        risk_reward=2.0, confidence=80.0, grade="A", score=80.0,
        net_rr_after_costs=1.8, status=SetupStatus.DISCOVERED.value,
        setup_type=SetupType.LIMIT.value, created_at_ms=now,
        updated_at_ms=now,
    )


def make_pool(tmp_path):
    return OpportunityPool(
        base_path=str(tmp_path / "pool"), auto_persist=False,
        expiry_hours=24,
    )


def test_invalidated_setup_is_removed_archived_and_can_be_added_again(tmp_path):
    pool = make_pool(tmp_path)
    original = candidate()
    assert pool.add_candidate(original)
    assert pool.validate_candidate(original.setup_id)

    assert pool.invalidate_setup(original.setup_id, "STRUCTURE_BROKEN")
    assert pool.get_setup(original.setup_id) is None
    assert pool.get_validated_setups(symbol=original.symbol) == []

    history = pool.get_recent_history(limit=5)
    archived = next(item for item in history if item["setup_id"] == original.setup_id)
    assert archived["status"] == SetupStatus.INVALIDATED.value
    assert archived["invalidation_reason"] == "STRUCTURE_BROKEN"

    # Removal is not a symbol/strategy blacklist: a later cycle can add it.
    renewed = candidate()
    renewed.created_at_ms += 1
    assert pool.add_candidate(renewed)
    assert pool.get_setup(renewed.setup_id) is renewed
    pool.stop()


def test_invalidate_setup_removes_active_and_validated_records(tmp_path):
    pool = make_pool(tmp_path)
    active = candidate("active")
    assert pool.add_candidate(active)
    assert pool.validate_candidate("active")
    assert pool.accept_setup("active", "user-1")
    assert pool.invalidate_setup("active", "ORDER_BLOCK_INVALIDATED")
    assert pool.get_active_setups() == []
    assert pool.get_setup("active") is None
    assert pool.get_recent_history(limit=1)[0]["invalidation_reason"] == "ORDER_BLOCK_INVALIDATED"
    pool.stop()


def test_runtime_invalidation_clears_symbol_snapshot_but_not_scan_eligibility(tmp_path, monkeypatch):
    import atlas_runtime

    pool = make_pool(tmp_path)
    item = candidate("runtime-setup")
    pool.add_candidate(item)
    pool.validate_candidate(item.setup_id)

    state = StateEngine(str(tmp_path / "atlas_state.json"))
    state.store_active_setup(item.symbol, {
        "signal": {"signal": "LONG", "confidence": 80},
        "risk": {"entry": 100.0, "stop_loss": 98.0, "tp1": 102.0},
        "decision": {"action": "EXECUTE"},
        "analysis": {},
    })
    runtime = AtlasRuntime.__new__(AtlasRuntime)
    runtime.engine = SimpleNamespace(state_engine=state)
    monkeypatch.setattr(atlas_runtime, "get_opportunity_pool", lambda: pool)

    assert runtime.invalidate_setup(item.setup_id, "FVG_STRUCTURE_BROKEN")
    assert state.get_active_setup(item.symbol) is None
    assert pool.get_setup(item.setup_id) is None

    # No scan queue mutation or symbol suppression is introduced by invalidation.
    assert pool.add_candidate(candidate("runtime-setup"))
    pool.stop()
