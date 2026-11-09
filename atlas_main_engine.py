"""Atlas main authority and shared specialist-evidence coordinator.

Flow: market data -> specialist motors -> shared evidence pool -> one setup
builder -> one final decision. Specialist motors publish evidence only; the
main engine owns setup construction and final decision authority.
"""
from collections import Counter
from copy import deepcopy


class MotorProxy:
    """Transparent adapter: every specialist call is executed and recorded by the main engine."""

    __slots__ = ("_main", "_name", "_target")

    def __init__(self, main, name, target):
        object.__setattr__(self, "_main", main)
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_target", target)

    def __getattr__(self, attribute):
        value = getattr(self._target, attribute)
        if not callable(value):
            return value

        def invoke(*args, **kwargs):
            return self._main.execute_motor(
                self._name, attribute, value, *args, **kwargs
            )
        invoke.__name__ = getattr(value, "__name__", attribute)
        return invoke

    def __setattr__(self, attribute, value):
        setattr(self._target, attribute, value)


class AtlasMainEngine:
    """Atlas'ın tek ana motoru: kanıtları toplar, setup kurar ve karar verir."""

    def __init__(self, *, motors, setup_reasoner, decision_engine):
        self.setup_reasoner = setup_reasoner
        self.decision_engine = decision_engine
        self.motors = {}
        self._targets = {}
        self.evidence_pool = []
        self.motor_errors = []
        self.motor_call_counts = Counter()
        self._sequence = 0
        self.last_motor_report = {}
        for name, target in dict(motors or {}).items():
            self.attach_motor(name, target)

    def attach_motor(self, name, target):
        """Register one specialist and return its transparent main-engine adapter."""
        if not name or target is None:
            raise ValueError("A named specialist motor instance is required")
        self._targets[name] = target
        proxy = MotorProxy(self, name, target)
        self.motors[name] = proxy
        return proxy

    def execute_motor(self, name, method, callable_, *args, **kwargs):
        """Run a specialist exactly once and place its raw output in shared evidence."""
        self._sequence += 1
        sequence = self._sequence
        self.motor_call_counts[name] += 1
        try:
            output = callable_(*args, **kwargs)
        except Exception as exc:
            record = {
                "sequence": sequence, "motor": name, "method": method,
                "status": "ERROR", "error": f"{type(exc).__name__}: {exc}",
            }
            self.evidence_pool.append(record)
            self.motor_errors.append(record)
            raise
        self.evidence_pool.append({
            "sequence": sequence, "motor": name, "method": method,
            "status": "COMPLETED", "output": output,
        })
        return output

    def reset_evidence(self):
        self.evidence_pool = []
        self.motor_errors = []
        self.motor_call_counts = Counter()
        self._sequence = 0

    def evidence_snapshot(self):
        """Return actual motor outputs in execution order for the setup authority."""
        return list(self.evidence_pool)

    def motor_diagnostics(self):
        expected = sorted(self.motors)
        invoked = sorted(name for name, count in self.motor_call_counts.items() if count)
        return {
            "expected_motors": expected,
            "invoked_motors": invoked,
            "not_invoked": sorted(set(expected) - set(invoked)),
            "call_counts": dict(self.motor_call_counts),
            "call_total": sum(self.motor_call_counts.values()),
            "error_count": len(self.motor_errors),
            "errors": list(self.motor_errors),
            "evidence_count": len(self.evidence_pool),
        }

    def analyze(self, market_data, *, pipeline):
        """Main engine controls lifecycle; pipeline is the ordered expert-analysis adapter."""
        if not callable(pipeline):
            raise TypeError("AtlasMainEngine requires a callable motor pipeline")
        self.reset_evidence()
        self.last_motor_report = {"pipeline": "RUNNING"}
        try:
            result = pipeline(market_data)
        except Exception:
            diagnostics = self.motor_diagnostics()
            self.last_motor_report.update({
                "registered_motors": diagnostics["expected_motors"],
                "pipeline": "FAILED",
                "motor_diagnostics": diagnostics,
            })
            raise
        diagnostics = self.motor_diagnostics()
        self.last_motor_report.update({
            "registered_motors": diagnostics["expected_motors"],
            "pipeline": "COMPLETED",
            "motor_diagnostics": diagnostics,
        })
        if isinstance(result, dict):
            analysis = result.get("analysis")
            if isinstance(analysis, dict):
                existing_diagnostics = analysis.get("motor_diagnostics")
                if not isinstance(existing_diagnostics, dict):
                    existing_diagnostics = {}
                existing_diagnostics["execution_trace"] = diagnostics
                analysis["motor_diagnostics"] = existing_diagnostics
            result["main_engine"] = {
                **self.last_motor_report,
                "evidence_pool_count": diagnostics["evidence_count"],
            }
        return result

    def build_setup(self, **motor_outputs):
        """The single setup construction point; all specialist evidence is passed here."""
        motor_outputs.setdefault("motor_evidence", self.evidence_snapshot())
        result = self.setup_reasoner.generate(**motor_outputs)
        result = result if isinstance(result, dict) else {
            "candidates": [], "selected": None,
            "reason": "Setup reasoning returned an invalid result",
        }
        candidates = result.get("candidates")
        result["candidates"] = candidates if isinstance(candidates, list) else []
        selected = result.get("selected")
        if not isinstance(selected, dict):
            result["selected"] = {
                "valid": False, "direction": "WAIT",
                "reason": result.get("reason") or "No coherent setup candidate",
            }
        result["decision_authority"] = "ATLAS_MAIN_ENGINE"
        self.last_motor_report.update({
            "registered_motors": sorted(self.motors),
            "setup_candidate_count": len(result["candidates"]),
            "selected_candidate_valid": bool(result["selected"].get("valid")),
            "setup_reason": result.get("reason"),
        })
        return result

    def decide(self, **motor_outputs):
        """Only final decision entry point."""
        decision = self.decision_engine.decide(**motor_outputs)
        decision = dict(decision or {})
        decision["decision_authority"] = "ATLAS_MAIN_ENGINE"
        decision["motor_registry_size"] = len(self.motors)
        self.last_motor_report["final_action"] = decision.get("action")
        self.last_motor_report["final_direction"] = decision.get("signal")
        return decision

    def apply_operational_gates(self, decision, *, news_filter=None,
                                correlation=None, cooldown=None):
        """Apply only operational hard gates; correlation remains evidence/warning."""
        enriched = deepcopy(decision or {})
        blockers, warnings = [], []
        for name, payload in (("news_filter", news_filter), ("cooldown", cooldown)):
            if isinstance(payload, dict) and payload.get("active", True) and not payload.get("trade_allowed", True):
                blockers.append(f"{name}: {payload.get('reason', 'blocked')}")
        if isinstance(correlation, dict) and correlation.get("active", True) and not correlation.get("trade_allowed", True):
            warnings.append(f"correlation: {correlation.get('reason', 'counterpressure; retained as evidence')}")
        if warnings:
            enriched["external_warnings"] = list(enriched.get("external_warnings") or []) + warnings
        if blockers:
            enriched["action"] = "SKIP"
            enriched["external_blockers"] = blockers
            enriched["critical_blockers"] = list(enriched.get("critical_blockers") or []) + blockers
            enriched["reason"] = "; ".join(blockers)
        enriched["decision_authority"] = "ATLAS_MAIN_ENGINE"
        self.last_motor_report["operational_blockers"] = blockers
        self.last_motor_report["operational_warnings"] = warnings
        return enriched
