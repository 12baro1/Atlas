from atlas_main_engine import AtlasMainEngine
from shared.specialist_evidence import attach_strategy_evidence, evidence_for_strategy


def test_main_engine_routes_only_completed_analysis_motors_to_strategies():
    main = AtlasMainEngine(
        motors={"orderbook": object(), "risk": object()},
        setup_reasoner=object(),
        decision_engine=object(),
    )
    main.execute_motor(
        "orderbook", "analyze",
        lambda: {"active": True, "event_id": "book-event-1"},
    )
    main.execute_motor(
        "risk", "evaluate",
        lambda: {"risk_setup_valid": True, "event_id": "risk-event-1"},
    )

    routed = main.strategy_evidence_snapshot()

    assert len(routed) == 1
    assert routed[0]["motor"] == "orderbook"
    assert routed[0]["event_ids"] == ["book-event-1"]


def test_strategy_receives_only_its_assigned_specialist_evidence():
    data = {
        "specialist_evidence": [
            {
                "motor": "orderbook", "method": "analyze",
                "status": "COMPLETED", "output": {"active": True},
                "event_ids": ["book-1"],
            },
            {
                "motor": "liquidity", "method": "analyze",
                "status": "COMPLETED", "output": {"pools": 3},
                "event_ids": ["liq-1"],
            },
            {
                "motor": "risk", "method": "evaluate",
                "status": "COMPLETED", "output": {"risk_setup_valid": True},
                "event_ids": ["risk-1"],
            },
        ]
    }

    orderflow = evidence_for_strategy(data, "orderflow_momentum")
    trend = evidence_for_strategy(data, "trend_pullback")

    assert {item["motor"] for item in orderflow} == {"orderbook", "liquidity"}
    assert {item["motor"] for item in trend} == {"liquidity"}
    assert all(item["motor"] != "risk" for item in orderflow + trend)


def test_generated_setup_records_specialist_provenance_without_raw_motor_objects():
    records = [
        {
            "motor": "orderbook", "method": "analyze",
            "status": "COMPLETED", "output": {"large": "raw output"},
            "event_ids": ["book-1"],
        }
    ]
    candidate = {"strategy_id": "orderflow_momentum", "reasons": ["native setup"]}
    attach_strategy_evidence(candidate, records)

    assert candidate["specialist_evidence_sources"] == ["orderbook"]
    assert candidate["specialist_evidence_count"] == 1
    assert candidate["specialist_evidence_event_ids"] == ["book-1"]
    assert "output" not in candidate["specialist_evidence"][0]


def test_strategy_data_usage_reports_shared_motor_availability():
    from strategy_lab import _strategy_data_usage

    usage = _strategy_data_usage(
        "orderflow_momentum",
        {
            "specialist_evidence": [
                {
                    "motor": "orderbook", "method": "analyze",
                    "status": "COMPLETED", "output": {"active": True},
                    "event_ids": ["book-1"],
                }
            ]
        },
    )

    assert usage["specialist_motor_inputs"]["orderbook"]["state"] == "AVAILABLE"
    assert usage["specialist_motor_inputs"]["liquidity"]["state"] == "NOT_INVOKED_OR_UNAVAILABLE"
