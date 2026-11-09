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
            decision = result.get("decision") or {}
            self.last_motor_report.setdefault("final_action", decision.get("action"))
            self.last_motor_report.setdefault("final_direction", decision.get("signal"))
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

    @staticmethod
    def _validate_execution_geometry(decision, *, entry, risk, targets, current_price,
                                     max_limit_distance_pct, max_market_distance_pct):
        """Final authority guard: never execute an impossible or stale price plan."""
        action = str((decision or {}).get("action") or "").upper()
        if action not in {"EXECUTE", "EXECUTE_WITH_CAUTION"}:
            return decision
        setup = entry if isinstance(entry, dict) else {}
        if setup.get("valid") is False:
            return {"action": "SKIP", "signal": str(setup.get("direction") or "WAIT").upper(),
                    "reason": f"Final validation: setup marked invalid ({setup.get('reason') or 'unspecified'})",
                    "critical_blockers": ["SETUP_INVALID"]}
        side = str(setup.get("direction") or (decision or {}).get("signal") or "").upper()
        if side not in {"LONG", "SHORT"}:
            return {"action": "SKIP", "signal": side or "WAIT",
                    "reason": "Final validation: missing/invalid trade direction",
                    "critical_blockers": ["INVALID_DIRECTION"]}
        try:
            current = float(current_price)
            price = float(setup.get("entry"))
            stop = float((risk or {}).get("stop_loss", setup.get("stop_loss")))
        except (TypeError, ValueError, OverflowError):
            return {"action": "SKIP", "signal": side,
                    "reason": "Final validation: missing/non-numeric current, entry or stop",
                    "critical_blockers": ["INVALID_PRICE_GEOMETRY"]}
        import math
        if not all(math.isfinite(v) and v > 0 for v in (current, price, stop)):
            return {"action": "SKIP", "signal": side,
                    "reason": "Final validation: non-finite/non-positive price",
                    "critical_blockers": ["INVALID_PRICE_GEOMETRY"]}
        order_type = str(setup.get("entry_type") or "MARKET").upper()
        if side == "LONG" and not stop < price:
            reason = "LONG stop must be below entry"
        elif side == "SHORT" and not stop > price:
            reason = "SHORT stop must be above entry"
        elif order_type == "LIMIT" and side == "LONG" and not price < current:
            reason = "LONG LIMIT must be below current price"
        elif order_type == "LIMIT" and side == "SHORT" and not price > current:
            reason = "SHORT LIMIT must be above current price"
        else:
            reason = None
        if reason:
            return {"action": "SKIP", "signal": side, "reason": f"Final validation: {reason}",
                    "critical_blockers": ["INVALID_PRICE_GEOMETRY"]}
        distance_pct = abs(price - current) / current
        # A valid pending LIMIT is a setup even when price is far away.
        # Distance is execution context, not a setup-validity veto. Keep the
        # far entry visible and label it; only reject a stale/far MARKET order.
        if order_type == "MARKET" and max_market_distance_pct is not None:
            if distance_pct > float(max_market_distance_pct):
                return {"action": "SKIP", "signal": side,
                        "reason": f"Final validation: MARKET entry too far from market ({distance_pct:.2%} > {float(max_market_distance_pct):.2%})",
                        "critical_blockers": ["MARKET_ENTRY_TOO_FAR"],
                        "entry_distance_percent": distance_pct}
        if order_type == "LIMIT":
            decision = dict(decision or {})
            decision["entry_distance_percent"] = distance_pct
            decision["entry_distance_label"] = "UZAK GİRİŞ" if distance_pct > 0.02 else "YAKIN GİRİŞ"
            decision["entry_execution_note"] = (
                "LIMIT beklemede; fiyat giriş bölgesine gelirse tetiklenir"
                if distance_pct > 0.02 else "LIMIT giriş bölgesi piyasaya yakın"
            )
        target_values = []
        for key in ("tp1", "tp2", "tp3"):
            value = (targets or {}).get(key) if isinstance(targets, dict) else None
            if value is not None:
                try:
                    value = float(value)
                except (TypeError, ValueError, OverflowError):
                    continue
                if math.isfinite(value) and value > 0:
                    target_values.append((key, value))
        if not target_values:
            return {"action": "SKIP", "signal": side,
                    "reason": "Final validation: no valid structural target",
                    "critical_blockers": ["NO_VALID_TARGET"]}
        invalid = [key for key, value in target_values
                   if (side == "LONG" and value <= price) or (side == "SHORT" and value >= price)]
        if invalid:
            return {"action": "SKIP", "signal": side,
                    "reason": "Final validation: target is not beyond entry in trade direction",
                    "critical_blockers": ["INVALID_TARGET_GEOMETRY"],
                    "invalid_targets": invalid}
        return decision

    def decide(self, **motor_outputs):
        """Only final decision entry point."""
        decision = self.decision_engine.decide(**motor_outputs)
        decision = dict(decision or {})
        if motor_outputs.get("current_price") is not None:
            decision = self._validate_execution_geometry(
                decision,
                entry=motor_outputs.get("entry"),
                risk=motor_outputs.get("risk"),
                targets=motor_outputs.get("targets"),
                current_price=motor_outputs.get("current_price"),
                max_limit_distance_pct=motor_outputs.get("max_limit_distance_pct", 0.05),
                max_market_distance_pct=motor_outputs.get("max_market_distance_pct", 0.003),
            )
        decision["decision_authority"] = "ATLAS_MAIN_ENGINE"
        decision["motor_registry_size"] = len(self.motors)
        diagnostics = self.motor_diagnostics()
        decision["motor_evidence_count"] = diagnostics["evidence_count"]
        decision["motor_evidence_sources"] = sorted({
            record["motor"] for record in self.evidence_pool
            if record.get("status") == "COMPLETED" and record.get("motor")
        })
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
        self.last_motor_report["final_action"] = enriched.get("action")
        self.last_motor_report["final_direction"] = enriched.get("signal")
        return enriched
