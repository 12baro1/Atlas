"""Runtime integration regressions: engine result shape -> pool, telemetry."""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from atlas_runtime import AtlasRuntime
from opportunity_pool import OpportunityPool, SetupStatus


def make_runtime():
    runtime = AtlasRuntime.__new__(AtlasRuntime)
    runtime._lock = __import__("threading").Lock()
    return runtime


def engine_shaped_result(symbol="BTC/USDT:USDT", direction="LONG", entry_type="LIMIT"):
    """Mirror the real engine.py result_payload structure.

    The selected setup lives ONLY in result['strategy_lab']['selected'];
    there is no top-level 'selected' key (the P0 regression fixed in this PR).
    """
    selected = {
        "strategy_id": "orderflow_momentum",
        "strategy": "Order Flow Momentum",
        "direction": direction,
        "entry_type": entry_type,
        "entry": 50000.0,
        "stop_loss": 49500.0,
        "tp1": 51000.0,
        "tp2": 52000.0,
        "tp3": 53000.0,
        "rr_tp1": 2.0,
        "rr_tp2": 4.0,
        "rr_tp3": 6.0,
        "strength": 78.0,
        "partial_exit_weights": {"tp1": 0.5, "tp2": 0.3, "tp3": 0.2},
        "estimated_net_rr": 1.9,
        "reasons": ["footprint absorption"],
        "supporting_event_ids": ["ev-1"],
        "opposing_event_ids": [],
        "status": "SELECTED",
    }
    return {
        "symbol": symbol,
        "trace_id": "trace-abc",
        "analysis": {"market_phase": {"phase": "Expansion"}},
        "strategy_lab": {
            "regime": "TREND",
            "selected": selected,
            "diagnostics": {
                "raw_setup_count": 4,
                "common_filter_passed_count": 2,
                "strategies": [
                    {"strategy_id": "smc", "status": "SELECTED", "selected": True},
                    {"strategy_id": "orderflow_momentum", "status": "FILTERED_NOT_SELECTED",
                     "selected": False, "rejection_reasons": ["Another eligible setup ranked higher"]},
                    {"strategy_id": "trend_pullback", "status": "BLOCKED_COMMON_FILTER",
                     "rejection_reasons": ["MARKET_ENTRY_TOO_FAR"]},
                ],
            },
        },
    }


def test_engine_result_shape_flows_into_pool(tmp_path):
    runtime = make_runtime()
    pool = OpportunityPool(base_path=str(tmp_path / "pool"), auto_persist=False)
    result = engine_shaped_result()

    # Exactly the runtime integration sequence in _analyze_symbol
    lab = result.get("strategy_lab") or {}
    selected = lab.get("selected")
    assert isinstance(selected, dict), "selected must come from strategy_lab"
    candidate = runtime._setup_to_candidate(
        selected, result["symbol"], trace_id=result.get("trace_id"),
        regime=lab.get("regime"),
        market_phase=result["analysis"]["market_phase"]["phase"],
    )
    assert candidate is not None
    assert pool.add_candidate(candidate) is True
    assert pool.validate_candidate(candidate.setup_id) is True

    best = pool.get_best_setups(limit=5)
    assert len(best) == 1
    stored = best[0]
    assert stored.symbol == "BTC/USDT:USDT"
    assert stored.strategy_id == "orderflow_momentum"
    assert stored.entry_type == "LIMIT"
    assert stored.setup_type == "LIMIT"
    assert stored.net_rr_after_costs == pytest.approx(1.9)
    assert stored.rr_tp1 == pytest.approx(2.0)
    assert stored.trace_id == "trace-abc"
    assert stored.market_phase == "Expansion"
    assert stored.status == SetupStatus.VALIDATED.value
    pool.stop()


def test_success_counter_incremented(tmp_path):
    runtime = make_runtime()
    runtime._scanner_stats = {
        "processed": 0, "success": 0, "failed": 0, "skipped": 0, "cycle": 0,
    }
    runtime._inc("success")
    assert runtime._scanner_stats["success"] == 1


def test_strategy_telemetry_accumulates_funnel(tmp_path):
    runtime = make_runtime()
    runtime._scanner_stats = {"processed": 0}
    runtime.logger = __import__("logging").getLogger("test")
    from collections import defaultdict
    runtime._strategy_telemetry = {
        "analyses": 0,
        "raw_setups_generated": 0,
        "common_filter_passed": 0,
        "common_filter_rejected": 0,
        "rejection_reasons": defaultdict(int),
        "per_strategy": defaultdict(lambda: {"setups": 0, "passed": 0, "rejected": 0, "selected": 0}),
    }

    runtime._accumulate_strategy_telemetry(engine_shaped_result())

    telemetry = runtime.strategy_telemetry()
    assert telemetry["analyses"] == 1
    assert telemetry["raw_setups_generated"] == 4
    assert telemetry["common_filter_passed"] == 2
    assert telemetry["common_filter_rejected"] == 2
    assert telemetry["rejection_reasons"]["MARKET_ENTRY_TOO_FAR"] == 1
    per_strategy = telemetry["per_strategy"]
    assert per_strategy["smc"]["selected"] == 1
    assert per_strategy["orderflow_momentum"]["passed"] == 1
    assert per_strategy["trend_pullback"]["rejected"] == 1


def test_second_analysis_of_same_setup_is_idempotent(tmp_path):
    """Re-scanning an unchanged setup must not duplicate pool records."""
    runtime = make_runtime()
    pool = OpportunityPool(base_path=str(tmp_path / "pool"), auto_persist=False)
    for _ in range(3):
        result = engine_shaped_result()
        lab = result["strategy_lab"]
        candidate = runtime._setup_to_candidate(
            lab["selected"], result["symbol"],
            regime=lab.get("regime"),
            market_phase=result["analysis"]["market_phase"]["phase"],
        )
        assert candidate is not None
        pool.add_candidate(candidate)
        pool.validate_candidate(candidate.setup_id)
    assert len(pool._validated) == 1
    assert pool.get_stats()["candidates"] == 0
    pool.stop()
