"""Regression checks for the 5 trade generators + 2 read-only specialists."""
from collections import defaultdict
from threading import RLock
from types import SimpleNamespace

from strategy_catalog import (
    TRADE_STRATEGY_IDS, SPECIALIST_IDS, TRADE_STRATEGY_LABELS, SPECIALIST_LABELS,
)
from strategy_outcome_journal import StrategyOutcomeJournal
from telegram_command_service import TelegramCommandService


def test_canonical_roles_are_distinct_and_have_expected_sizes():
    assert len(TRADE_STRATEGY_IDS) == 5
    assert len(SPECIALIST_IDS) == 2
    assert not (TRADE_STRATEGY_IDS & SPECIALIST_IDS)
    assert set(TRADE_STRATEGY_LABELS) == TRADE_STRATEGY_IDS
    assert set(SPECIALIST_LABELS) == SPECIALIST_IDS


def test_telegram_motors_and_stats_do_not_count_specialists_as_setup_generators():
    report = {
        "strategy_telemetry": {
            "analyses": 4,
            "raw_setups_generated": 1,
            "common_filter_passed": 1,
            "common_filter_rejected": 0,
            "per_strategy": {
                "smc": {"analyses": 4, "setups": 1, "passed": 1, "selected": 1},
                # Old/invalid counters must not turn this specialist into a sixth generator.
                "relative_strength": {"setups": 20, "passed": 20},
            },
            "specialists": {
                "relative_strength": {"analyses": 4, "last_state": "AVAILABLE"},
                "liquidation_cascade": {"analyses": 4, "last_state": "UNAVAILABLE"},
            },
        },
        "pool_validations": {"smc": 1, "relative_strength": 99},
    }
    bot = TelegramCommandService(None, "token", "123")
    bot.runtime = SimpleNamespace(scan_status=lambda: report)
    motors = bot.handle_motors()
    stats = bot.handle_statistics()
    assert "5 İŞLEM STRATEJİSİ + 2 ANALİZ UZMANI" in motors
    assert "ANALİZ UZMANLARI" in motors
    assert "RELATIVE STRENGTH: analiz=4" in motors
    assert "LIQUIDATION CASCADE: analiz=4" in motors
    assert "20 setup" not in motors + stats
    assert "99" not in motors
    assert "sadece kanıt" in stats.lower() or "setup üretmez" in stats.lower()


def test_runtime_telemetry_keeps_specialist_evidence_out_of_trade_counters():
    from atlas_runtime import AtlasRuntime

    runtime = AtlasRuntime.__new__(AtlasRuntime)
    runtime._lock = RLock()
    runtime.logger = SimpleNamespace(debug=lambda *args: None)
    runtime._strategy_telemetry = {
        "analyses": 0,
        "raw_setups_generated": 0,
        "common_filter_passed": 0,
        "common_filter_rejected": 0,
        "rejection_reasons": defaultdict(int),
        "per_strategy": defaultdict(lambda: {
            "setups": 0, "passed": 0, "rejected": 0, "selected": 0,
            "no_setup": 0, "condition_not_met": 0, "missing_data": 0,
            "insufficient_history": 0, "errors": 0, "other_no_setup": 0,
            "reason_counts": defaultdict(int),
        }),
        "specialists": {},
    }
    runtime._accumulate_strategy_telemetry({
        "strategy_lab": {
            "diagnostics": {
                "raw_setup_count": 0,
                "strategies": [
                    {"strategy_id": "smc", "status": "NO_SETUP"},
                    {"strategy_id": "relative_strength", "status": "SELECTED",
                     "direction": "LONG", "selected": True},
                ],
            },
            "specialist_evidence": {
                "relative_strength": {"state": "AVAILABLE", "setup_generation": False},
                "liquidation_cascade": {"state": "UNAVAILABLE", "setup_generation": False},
            },
        },
    })
    snapshot = runtime.strategy_telemetry()
    assert set(snapshot["per_strategy"]) == {"smc"}
    assert snapshot["per_strategy"]["smc"]["no_setup"] == 1
    assert snapshot["specialists"]["relative_strength"]["last_state"] == "AVAILABLE"
    assert snapshot["specialists"]["liquidation_cascade"]["last_state"] == "UNAVAILABLE"


def test_specialist_outcomes_are_not_accepted_as_realized_trade_performance(tmp_path):
    journal = StrategyOutcomeJournal(str(tmp_path / "outcomes.jsonl"))
    payload = dict(
        trade_id="t1", run_id="run1", run_created_at_ms=1000, split="oos",
        net_r=0.9, gross_r=1.0, cost_r=0.1, cost_model_id="cost-v1",
        closed_at_ms=1000, costs_included=True,
    )
    for specialist_id in SPECIALIST_IDS:
        result = journal.record_outcome(strategy_id=specialist_id, **payload)
        assert result["accepted"] is False
    assert journal.performance_snapshot() == {}
