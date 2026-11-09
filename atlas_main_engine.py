"""Single authority for Atlas setup construction and final trade decisions.

Specialist engines remain focused analysis motors. AtlasMainEngine owns their
registry and is the only public coordinator used by AtlasEngine for setup
reasoning and final decision output. It does not duplicate their calculations.
"""

from copy import deepcopy


class AtlasMainEngine:
    """Atlas'ın büyük patron motoru: motor kanıtlarını tek işlem planında birleştirir."""

    def __init__(self, *, motors, setup_reasoner, decision_engine):
        self.motors = dict(motors or {})
        self.setup_reasoner = setup_reasoner
        self.decision_engine = decision_engine
        self.last_motor_report = {}

    def analyze(self, market_data, *, pipeline):
        """Own the complete analysis lifecycle; pipeline executes registered motors."""
        if not callable(pipeline):
            raise TypeError("AtlasMainEngine requires a callable motor pipeline")
        self.last_motor_report = {
            "registered_motors": sorted(self.motors),
            "pipeline": "RUNNING",
        }
        result = pipeline(market_data)
        self.last_motor_report["pipeline"] = "COMPLETED"
        if isinstance(result, dict):
            decision = result.get("decision") or {}
            result["main_engine"] = {
                **self.last_motor_report,
                "final_action": decision.get("action"),
                "final_direction": decision.get("signal"),
            }
        return result

    def build_setup(self, **motor_outputs):
        """Run the setup-construction motor with the complete specialist evidence."""
        result = self.setup_reasoner.generate(**motor_outputs)
        result = result if isinstance(result, dict) else {
            "candidates": [],
            "selected": None,
            "reason": "Setup reasoning returned an invalid result",
        }
        candidates = result.get("candidates")
        result["candidates"] = candidates if isinstance(candidates, list) else []
        selected = result.get("selected")
        if not isinstance(selected, dict):
            result["selected"] = {
                "valid": False,
                "direction": "WAIT",
                "reason": result.get("reason") or "No coherent setup candidate",
            }
        self.last_motor_report = {
            "registered_motors": sorted(self.motors),
            "setup_candidate_count": len(result["candidates"]),
            "selected_candidate_valid": bool(result["selected"].get("valid")),
            "setup_reason": result.get("reason"),
        }
        return result

    def decide(self, **motor_outputs):
        """The only final-decision entry point used by the top-level Atlas engine."""
        decision = self.decision_engine.decide(**motor_outputs)
        decision = dict(decision or {})
        decision["decision_authority"] = "ATLAS_MAIN_ENGINE"
        decision["motor_registry_size"] = len(self.motors)
        self.last_motor_report["final_action"] = decision.get("action")
        self.last_motor_report["final_direction"] = decision.get("signal")
        return decision

    def apply_operational_gates(self, decision, *, news_filter=None,
                                correlation=None, cooldown=None):
        """Apply operational safety gates after the main setup decision.

        Specialist market evidence is not converted into duplicate vetoes.
        Only macro-news protection and duplicate-position cooldown are hard
        operational gates; correlation remains a warning.
        """
        enriched = deepcopy(decision or {})
        blockers = []
        warnings = []
        for name, payload in (("news_filter", news_filter), ("cooldown", cooldown)):
            if not isinstance(payload, dict):
                continue
            if not payload.get("active", True):
                continue
            if not payload.get("trade_allowed", True):
                blockers.append(f"{name}: {payload.get('reason', 'blocked')}")

        if isinstance(correlation, dict) and correlation.get("active", True):
            if not correlation.get("trade_allowed", True):
                warnings.append(
                    f"correlation: {correlation.get('reason', 'counterpressure; retained as evidence')}"
                )

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
