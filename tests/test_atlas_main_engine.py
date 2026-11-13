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


def test_stable_event_ids_are_tracked_across_specialist_motors():
    class _Motor:
        def detect(self):
            return {"events": [{"event_id": "15m:structure:t1700000000000:LOW:100:true"}]}

    main = AtlasMainEngine(
        motors={"structure": _Motor(), "liquidity": _Motor()},
        setup_reasoner=_SetupReasoner(),
        decision_engine=_Decision(),
    )
    main.motors["structure"].detect()
    main.motors["liquidity"].detect()

    diagnostics = main.motor_diagnostics()["event_identity"]
    assert diagnostics["unique"] == 1
    assert diagnostics["duplicate_ids"] == 1
    assert diagnostics["cross_motor_duplicate_ids"] == 1
    assert main.evidence_snapshot()[0]["event_ids"] == [
        "15m:structure:t1700000000000:LOW:100:true"
    ]


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



def test_final_action_report_reflects_operational_gate_override():
    main, _ = _main()
    main.decide(signal={"signal": "LONG"}, entry={"valid": True})
    result = main.apply_operational_gates(
        {"action": "EXECUTE", "signal": "LONG"},
        news_filter={"active": True, "trade_allowed": False, "reason": "high impact"},
    )
    assert result["action"] == "SKIP"
    assert main.last_motor_report["final_action"] == "SKIP"
    assert main.last_motor_report["final_direction"] == "LONG"



def test_final_decision_contains_full_shared_evidence_lineage():
    class _Motor:
        def detect(self):
            return {"structure": "confirmed"}

    main = AtlasMainEngine(
        motors={"structure": _Motor()},
        setup_reasoner=_SetupReasoner(),
        decision_engine=_Decision(),
    )
    main.motors["structure"].detect()
    result = main.decide(signal={"signal": "LONG"}, entry={"valid": True})

    assert result["motor_evidence_count"] == 1
    assert result["motor_evidence_sources"] == ["structure"]

def test_main_engine_keeps_valid_far_limit_setup_and_labels_distance():
    main, _ = _main()
    result = main.decide(
        signal={"signal": "SHORT"}, entry={
            "valid": True, "direction": "SHORT", "entry": 113668.68,
            "stop_loss": 113709.40, "entry_type": "LIMIT",
        }, risk={"stop_loss": 113709.40},
        targets={"tp1": 75150, "tp2": 74810, "tp3": 73400},
        current_price=75100, max_limit_distance_pct=0.05,
        max_market_distance_pct=0.003,
    )
    assert result["action"] == "EXECUTE"
    assert result["entry_distance_label"] == "UZAK GİRİŞ"
    assert result["entry_distance_percent"] > 0.05


def test_main_engine_still_blocks_far_market_execution():
    main, _ = _main()
    result = main.decide(
        signal={"signal": "LONG"}, entry={
            "valid": True, "direction": "LONG", "entry": 110,
            "stop_loss": 95, "entry_type": "MARKET",
        }, risk={"stop_loss": 95}, targets={"tp1": 120},
        current_price=100, max_limit_distance_pct=0.05,
        max_market_distance_pct=0.003,
    )
    assert result["action"] == "SKIP"
    assert "MARKET_ENTRY_TOO_FAR" in result["critical_blockers"]


def test_main_engine_final_authority_blocks_target_on_wrong_side_of_entry():
    main, _ = _main()
    result = main.decide(
        signal={"signal": "SHORT"}, entry={
            "valid": True, "direction": "SHORT", "entry": 100,
            "stop_loss": 105, "entry_type": "LIMIT",
        }, risk={"stop_loss": 105}, targets={"tp1": 110},
        current_price=99, max_limit_distance_pct=0.05,
        max_market_distance_pct=0.003,
    )
    assert result["action"] == "SKIP"
    assert "INVALID_TARGET_GEOMETRY" in result["critical_blockers"]


def test_main_engine_final_authority_allows_coherent_nearby_limit():
    main, _ = _main()
    result = main.decide(
        signal={"signal": "SHORT"}, entry={
            "valid": True, "direction": "SHORT", "entry": 101,
            "stop_loss": 103, "entry_type": "LIMIT",
        }, risk={"stop_loss": 103}, targets={"tp1": 98, "tp2": 95},
        current_price=100, max_limit_distance_pct=0.05,
        max_market_distance_pct=0.003,
    )
    assert result["action"] == "EXECUTE"


def test_main_engine_selects_best_executable_candidate_not_reasoner_choice():
    class _CompetingReasoner:
        def generate(self, **kwargs):
            return {
                "candidates": [
                    {
                        "valid": True, "execution_eligible": True, "direction": "LONG",
                        "setup_candidate_id": "lower-quality", "net_first_target_rr": 0.8,
                        "net_projected_rr": 1.8, "entry_distance_pct": 0.5,
                    },
                    {
                        "valid": True, "execution_eligible": True, "direction": "SHORT",
                        "setup_candidate_id": "best-quality", "net_first_target_rr": 1.2,
                        "net_projected_rr": 2.6, "entry_distance_pct": 1.0,
                        "execution_economics_valid": True, "structure_aligned": True,
                    },
                ],
                "selected": {"valid": False, "direction": "WAIT", "reason": "reasoner fallback"},
            }

    main = AtlasMainEngine(
        motors={},
        setup_reasoner=_CompetingReasoner(),
        decision_engine=_Decision(),
    )
    result = main.build_setup(current_price=100.0)
    assert result["selected"]["setup_candidate_id"] == "best-quality"
    assert result["selected"]["selected_by"] == "ATLAS_MAIN_ENGINE"
    assert main.last_motor_report["selected_candidate_valid"] is True


def test_main_engine_finalizes_stop_and_structural_tp_ladder():
    entry = {
        "valid": True, "direction": "LONG", "entry": 100.0,
        "stop_loss": 96.0, "tp1": 110.0, "tp2": 105.0, "tp3": 105.5,
    }
    risk = {"risk_setup_valid": True, "stop_loss": 95.0}
    targets = {
        "tp1": 110.0, "tp2": 105.0, "tp3": 105.5,
        "minimum_target_separation": 2.0,
    }
    result = AtlasMainEngine.finalize_setup_geometry(entry, risk, targets)
    assert result["entry"]["stop_loss"] == 95.0
    assert result["entry"]["tp1"] == 105.0
    assert result["entry"]["tp2"] == 110.0
    assert result["entry"]["tp3"] is None
    assert result["risk"]["stop_loss"] == 95.0
    assert result["targets"]["selected_by"] == "ATLAS_MAIN_ENGINE"
    assert result["entry"]["final_geometry_authority"] == "ATLAS_MAIN_ENGINE"


def test_main_engine_rejects_final_geometry_with_stop_on_wrong_side():
    result = AtlasMainEngine.finalize_setup_geometry(
        {"valid": True, "direction": "LONG", "entry": 100.0, "stop_loss": 101.0},
        {"risk_setup_valid": False},
        {"tp1": 105.0},
    )
    assert result["entry"]["valid"] is False
    assert result["entry"]["entry_reason_code"] == "INVALID_FINAL_STOP"


def test_main_engine_rejects_risk_entry_mismatch_before_publishing_geometry():
    result = AtlasMainEngine.finalize_setup_geometry(
        {"valid": True, "direction": "LONG", "entry": 100.0, "stop_loss": 95.0},
        {"risk_setup_valid": True, "entry": 101.0, "stop_loss": 95.0},
        {"tp1": 105.0},
    )
    assert result["entry"]["valid"] is False
    assert result["entry"]["entry_reason_code"] == "RISK_ENTRY_MISMATCH"


def test_main_geometry_preserves_missing_risk_payload():
    result = AtlasMainEngine.finalize_setup_geometry(
        {"valid": True, "direction": "LONG", "entry": 100.0, "stop_loss": 95.0},
        None,
        {"tp1": 105.0},
    )
    assert result["risk"] is None
    assert result["entry"]["valid"] is True
    assert result["entry"]["tp1"] == 105.0
