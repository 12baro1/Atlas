from atlas_main_engine import AtlasMainEngine


class _SetupReasoner:
    def generate(self, **kwargs):
        return {
            "candidates": [{"valid": True, "direction": "LONG"}],
            "selected": {"valid": True, "direction": "LONG"},
            "reason": "coherent POI",
        }


class _Decision:
    def __init__(self):
        self.calls = []

    def decide(self, **kwargs):
        self.calls.append(kwargs)
        return {"action": "EXECUTE", "signal": "LONG"}


def _main():
    decision = _Decision()
    motors = {"structure": object(), "liquidity": object(), "smt": object()}
    main = AtlasMainEngine(
        motors=motors,
        setup_reasoner=_SetupReasoner(),
        decision_engine=decision,
    )
    return main, decision


def test_main_engine_owns_specialist_registry_and_builds_setup():
    main, _ = _main()
    result = main.build_setup(mtf={"entry": "LONG"}, fvg=[{"type": "BULLISH"}])

    assert set(main.motors) == {"structure", "liquidity", "smt"}
    assert result["selected"]["valid"] is True
    assert main.last_motor_report["setup_candidate_count"] == 1


def test_main_engine_is_single_final_decision_entrypoint():
    main, decision = _main()
    result = main.decide(signal={"signal": "LONG"}, entry={"valid": True})

    assert len(decision.calls) == 1
    assert result["action"] == "EXECUTE"
    assert result["decision_authority"] == "ATLAS_MAIN_ENGINE"
    assert result["motor_registry_size"] == 3


def test_operational_gate_keeps_correlation_soft_and_news_hard():
    main, _ = _main()
    base = {"action": "EXECUTE", "critical_blockers": []}
    soft = main.apply_operational_gates(
        base,
        correlation={"active": True, "trade_allowed": False, "reason": "opposing market"},
    )
    assert soft["action"] == "EXECUTE"
    assert soft["external_warnings"]

    hard = main.apply_operational_gates(
        base,
        news_filter={"active": True, "trade_allowed": False, "reason": "high impact"},
    )
    assert hard["action"] == "SKIP"
    assert any("news_filter" in item for item in hard["critical_blockers"])


def test_missing_selected_candidate_is_normalized_to_invalid_setup():
    class _BrokenReasoner:
        def generate(self, **kwargs):
            return {"candidates": None, "selected": None}

    main = AtlasMainEngine(
        motors={},
        setup_reasoner=_BrokenReasoner(),
        decision_engine=_Decision(),
    )
    result = main.build_setup()
    assert result["candidates"] == []
    assert result["selected"]["valid"] is False
