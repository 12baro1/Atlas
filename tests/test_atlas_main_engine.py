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

def test_main_engine_owns_full_pipeline_lifecycle():
    main, _ = _main()
    calls = []
    payload = {"decision": {"action": "EXECUTE", "signal": "SHORT"}}

    def pipeline(data):
        calls.append(data)
        return payload

    result = main.analyze({"symbol": "BTC/USDT"}, pipeline=pipeline)
    assert calls == [{"symbol": "BTC/USDT"}]
    assert result["main_engine"]["pipeline"] == "COMPLETED"
    assert result["main_engine"]["final_action"] == "EXECUTE"
    assert result["main_engine"]["final_direction"] == "SHORT"


def test_main_engine_rejects_missing_pipeline():
    main, _ = _main()
    try:
        main.analyze({"symbol": "BTC/USDT"}, pipeline=None)
    except TypeError as exc:
        assert "callable motor pipeline" in str(exc)
    else:
        raise AssertionError("missing pipeline must fail explicitly")



def test_specialist_calls_are_executed_once_and_recorded_in_shared_evidence_pool():
    class _Motor:
        def detect(self, value):
            return {"level": value * 2}

    main = AtlasMainEngine(
        motors={"liquidity": _Motor(), "smt": object()},
        setup_reasoner=_SetupReasoner(),
        decision_engine=_Decision(),
    )
    result = main.motors["liquidity"].detect(7)
    diagnostics = main.motor_diagnostics()

    assert result == {"level": 14}
    assert diagnostics["call_counts"] == {"liquidity": 1}
    assert diagnostics["invoked_motors"] == ["liquidity"]
    assert diagnostics["not_invoked"] == ["smt"]
    assert main.evidence_snapshot()[0]["output"] == {"level": 14}


def test_specialist_exception_is_recorded_and_not_silently_swallowed():
    class _BrokenMotor:
        def detect(self):
            raise ValueError("bad motor output")

    main = AtlasMainEngine(
        motors={"broken": _BrokenMotor()},
        setup_reasoner=_SetupReasoner(),
        decision_engine=_Decision(),
    )
    try:
        main.motors["broken"].detect()
    except ValueError as exc:
        assert "bad motor output" in str(exc)
    else:
        raise AssertionError("motor exception must propagate")

    diagnostics = main.motor_diagnostics()
    assert diagnostics["error_count"] == 1
    assert diagnostics["errors"][0]["motor"] == "broken"
    assert diagnostics["errors"][0]["status"] == "ERROR"


def test_setup_builder_receives_shared_evidence_pool():
    class _CaptureReasoner:
        def __init__(self):
            self.kwargs = None

        def generate(self, **kwargs):
            self.kwargs = kwargs
            return {
                "candidates": [{"valid": True, "direction": "LONG"}],
                "selected": {"valid": True, "direction": "LONG"},
            }

    reasoner = _CaptureReasoner()
    main = AtlasMainEngine(
        motors={"structure": object()},
        setup_reasoner=reasoner,
        decision_engine=_Decision(),
    )
    main.evidence_pool.append({
        "sequence": 1, "motor": "structure", "method": "detect",
        "status": "COMPLETED", "output": {"bias": "BULLISH"},
    })
    main.build_setup(mtf={"entry": "LONG"})

    assert reasoner.kwargs["motor_evidence"][0]["output"] == {"bias": "BULLISH"}


def test_analysis_keeps_existing_diagnostics_and_adds_actual_motor_trace():
    main, _ = _main()
    payload = {
        "analysis": {"motor_diagnostics": {"motor_outputs": {"mtf": {"entry": "LONG"}}}},
        "decision": {"action": "EXECUTE", "signal": "LONG"},
    }

    def pipeline(_data):
        main.motors["structure"]  # registered specialist remains available to pipeline
        return payload

    result = main.analyze({"symbol": "BTC/USDT"}, pipeline=pipeline)
    diagnostics = result["analysis"]["motor_diagnostics"]

    assert diagnostics["motor_outputs"]["mtf"]["entry"] == "LONG"
    assert diagnostics["execution_trace"]["not_invoked"] == ["liquidity", "smt", "structure"]
    assert result["main_engine"]["evidence_pool_count"] == 0



def test_analysis_report_preserves_single_setup_and_final_decision():
    main, _ = _main()
    payload = {"decision": {"action": "EXECUTE", "signal": "LONG"}}

    def pipeline(_data):
        main.build_setup(mtf={"entry": "LONG"})
        main.decide(signal={"signal": "LONG"}, entry={"valid": True})
        return payload

    result = main.analyze({"symbol": "BTC/USDT"}, pipeline=pipeline)

    assert result["main_engine"]["setup_candidate_count"] == 1
    assert result["main_engine"]["selected_candidate_valid"] is True
    assert result["main_engine"]["final_action"] == "EXECUTE"
    assert result["main_engine"]["final_direction"] == "LONG"



def test_analysis_failure_keeps_motor_error_report():
    class _BrokenMotor:
        def analyze(self, _data):
            raise RuntimeError("specialist failed")

    main = AtlasMainEngine(
        motors={"broken": _BrokenMotor()},
        setup_reasoner=_SetupReasoner(),
        decision_engine=_Decision(),
    )

    def pipeline(data):
        return main.motors["broken"].analyze(data)

    try:
        main.analyze({"symbol": "BTC/USDT"}, pipeline=pipeline)
    except RuntimeError as exc:
        assert "specialist failed" in str(exc)
    else:
        raise AssertionError("failed specialist must abort analysis")

    assert main.last_motor_report["pipeline"] == "FAILED"
    assert main.last_motor_report["motor_diagnostics"]["error_count"] == 1
