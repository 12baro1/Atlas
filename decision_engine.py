"""
decision_engine.py
Atlas Decision Engine v3
"""

from config import Config


class DecisionEngine:
    """Atlas içindeki tüm modülleri birleştirerek nihai işlem kararını üretir."""

    ACTION_EXECUTE = "EXECUTE"
    ACTION_EXECUTE_WITH_CAUTION = "EXECUTE_WITH_CAUTION"
    ACTION_WAIT = "WAIT"
    ACTION_SKIP = "SKIP"

    def decide(self, analysis=None, **kwargs):
        """Bundle tabanlı karar üretir; eski kwargs tabanlı çağrıları da destekler."""
        context = self._normalize_context(analysis, kwargs)

        signal = context["signal"]
        confluence = context["confluence"]
        entry = context["entry"]
        risk = context["risk"]
        mtf = context["mtf"]
        ote = context["ote"]
        htf_orderblock = context["htf_orderblock"]
        liquidity_sweep = context["liquidity_sweep"]
        cisd = context["cisd"]
        volume_profile = context["volume_profile"]
        institutional = context["institutional"]
        unicorn = context["unicorn"]
        smt = context["smt"]
        market_phase = context["market_phase"]

        signal_dir = self._normalize_direction(signal.get("signal", "WAIT"))
        signal_confidence = self._safe_number(signal.get("confidence"), 0.0)
        signal_grade = str(signal.get("grade", "")).strip().upper()
        signal_strength = str(signal.get("strength", "")).strip().upper()
        confluence_score = self._clamp_score(self._safe_number(confluence.get("score"), 0.0))
        entry_valid = bool(entry.get("valid", False))

        minimum_rr = float(getattr(Config, "MINIMUM_RR", 3.0))
        minimum_confidence = float(getattr(Config, "MINIMUM_CONFIDENCE", 80))
        execute_threshold = float(getattr(Config, "DECISION_SCORE_EXECUTE", 90))
        caution_threshold = float(getattr(Config, "DECISION_SCORE_EXECUTE_WITH_CAUTION", 75))
        wait_threshold = float(getattr(Config, "DECISION_SCORE_WAIT", 60))

        rr_value = self._safe_number(risk.get("rr") if isinstance(risk, dict) else None, None)
        position_size = self._safe_number(risk.get("position_size") if isinstance(risk, dict) else None, None)

        risk_blockers, risk_valid = self._collect_risk_blockers(
            risk=risk,
            rr_value=rr_value,
            minimum_rr=minimum_rr,
            position_size=position_size,
        )

        critical_blockers = []
        self._append_unique(critical_blockers, "Signal direction invalid" if signal_dir not in ["LONG", "SHORT"] else None)
        self._append_unique(critical_blockers, "Entry invalid" if not entry_valid else None)
        self._append_unique(
            critical_blockers,
            f"Confidence below minimum: {self._fmt_number(signal_confidence)} < {self._fmt_number(minimum_confidence)}"
            if signal_confidence < minimum_confidence
            else None,
        )
        for blocker in risk_blockers:
            self._append_unique(critical_blockers, blocker)

        adjustments = self._collect_adjustments(
            signal_grade=signal_grade,
            signal_strength=signal_strength,
            signal_confidence=signal_confidence,
            rr_value=rr_value,
            minimum_rr=minimum_rr,
            direction=signal_dir,
            mtf=mtf,
            cisd=cisd,
            volume_profile=volume_profile,
            institutional=institutional,
            unicorn=unicorn,
            smt=smt,
            liquidity_sweep=liquidity_sweep,
            ote=ote,
            htf_orderblock=htf_orderblock,
            confluence=confluence,
        )

        total_score = self._clamp_score(confluence_score + sum(item["delta"] for item in adjustments))
        bonuses = [item for item in adjustments if item["delta"] > 0]
        soft_blockers = [item for item in adjustments if item["delta"] < 0]
        override_applies = self._high_quality_mismatch_override(
            signal_grade=signal_grade,
            signal_strength=signal_strength,
            signal_confidence=signal_confidence,
            rr_value=rr_value,
            soft_blockers=soft_blockers,
        )

        if critical_blockers:
            action = self.ACTION_SKIP
        elif override_applies:
            action = self.ACTION_EXECUTE
        elif total_score >= execute_threshold:
            action = self.ACTION_EXECUTE
        elif total_score >= caution_threshold:
            action = self.ACTION_EXECUTE_WITH_CAUTION
        elif total_score >= wait_threshold:
            action = self.ACTION_WAIT
        else:
            action = self.ACTION_SKIP

        reason = self._build_decision_reason(
            score=total_score,
            bonuses=bonuses,
            soft_blockers=soft_blockers,
            critical_blockers=critical_blockers,
            action=action,
            override_applies=override_applies,
        )

        return {
            "action": action,
            "reason": reason,
            "signal": signal_dir,
            "confidence": signal_confidence,
            "score": total_score,
            "base_score": confluence_score,
            "confluence_score": confluence_score,
            "entry_valid": entry_valid,
            "risk_valid": risk_valid,
            "rr": rr_value,
            "minimum_rr": minimum_rr,
            "critical_blockers": critical_blockers,
            "soft_blockers": soft_blockers,
            "bonuses": bonuses,
            "cisd_active": bool(cisd.get("active", False)),
            "cisd_direction": cisd.get("direction", "NONE"),
            "cisd_match": self._match_direction(cisd, signal_dir),
            "volume_profile_active": bool(volume_profile.get("active", False)),
            "volume_profile_direction": volume_profile.get("direction", "NONE"),
            "volume_profile_match": self._match_direction(volume_profile, signal_dir),
            "institutional_active": bool(institutional.get("active", False)),
            "institutional_direction": institutional.get("direction", "NONE"),
            "institutional_match": self._match_direction(institutional, signal_dir),
            "unicorn_active": bool(unicorn.get("active", False)),
            "unicorn_direction": self._extract_direction(unicorn),
            "smt_active": bool(smt.get("active", False)),
            "smt_direction": smt.get("direction", "NONE"),
            "market_phase": market_phase.get("phase", "Ranging"),
            "liquidity_sweep_strength": liquidity_sweep.get("strength_score", 0),
            "module_scores": {"decision_adjustments": adjustments},
        }

    def _normalize_context(self, analysis, kwargs):
        """Eski kwargs ve yeni analysis bundle çağrılarını tek formata dönüştürür."""
        bundle = {}

        if isinstance(analysis, dict):
            bundle.update(analysis)

        bundle.update(kwargs)

        signal = bundle.get("signal") or {}
        confluence = bundle.get("confluence") or {}
        entry = bundle.get("entry") or {}
        risk = bundle.get("risk")
        cisd = bundle.get("cisd") or {}
        volume_profile = bundle.get("volume_profile") or {}
        institutional = bundle.get("institutional") or {}
        unicorn = bundle.get("unicorn") or {}
        smt = bundle.get("smt") or {}
        mtf = bundle.get("mtf") or {}
        ote = bundle.get("ote") or {}
        htf_orderblock = bundle.get("htf_orderblock") or {}
        liquidity_sweep = bundle.get("liquidity_sweep") or {}
        market_phase = bundle.get("market_phase") or {}

        modules = bundle.get("modules") or self._discover_modules(bundle)

        return {
            "signal": signal,
            "confluence": confluence,
            "entry": entry,
            "risk": risk,
            "mtf": mtf,
            "ote": ote,
            "htf_orderblock": htf_orderblock,
            "liquidity_sweep": liquidity_sweep,
            "market_phase": market_phase,
            "cisd": cisd,
            "volume_profile": volume_profile,
            "institutional": institutional,
            "unicorn": unicorn,
            "smt": smt,
            "modules": modules,
        }

    def _discover_modules(self, bundle):
        """Future modules için üst seviye dict alanlarını otomatik toplar."""
        ignored = {
            "signal",
            "confluence",
            "entry",
            "risk",
            "mtf",
            "ote",
            "htf_orderblock",
            "liquidity_sweep",
            "market_phase",
            "cisd",
            "volume_profile",
            "institutional",
            "unicorn",
            "smt",
            "modules",
            "analysis",
            "decision",
        }

        discovered = {}
        for key, value in bundle.items():
            if key in ignored:
                continue
            if isinstance(value, dict):
                discovered[key] = value
        return discovered

    def _collect_risk_blockers(self, risk, rr_value, minimum_rr, position_size):
        blockers = []

        if risk is None:
            return ["Risk cannot be calculated", "Stop Loss invalid", "Position size invalid"], False

        if risk.get("risk_setup_valid") is False:
            self._append_unique(blockers, risk.get("risk_setup_reason") or "Invalid Risk Setup")
            return blockers, False

        risk_amount = self._safe_number(risk.get("risk"), None)
        stop_loss = self._safe_number(risk.get("stop_loss"), None)

        if risk_amount is None or risk_amount <= 0:
            self._append_unique(blockers, "Risk cannot be calculated")

        if stop_loss is None:
            self._append_unique(blockers, "Stop Loss invalid")

        if position_size is None or position_size <= 0:
            self._append_unique(blockers, "Position size invalid")

        if rr_value is None:
            self._append_unique(blockers, "Risk cannot be calculated")
        elif rr_value < minimum_rr:
            self._append_unique(
                blockers,
                f"RR below minimum RR: {self._fmt_number(rr_value)} < {self._fmt_number(minimum_rr)}",
            )

        return blockers, len(blockers) == 0

    def _collect_adjustments(
        self,
        signal_grade,
        signal_strength,
        signal_confidence,
        rr_value,
        minimum_rr,
        direction,
        mtf,
        cisd,
        volume_profile,
        institutional,
        unicorn,
        smt,
        liquidity_sweep,
        ote,
        htf_orderblock,
        confluence,
    ):
        adjustments = []

        if signal_grade == "S+":
            self._add_adjustment(adjustments, Config.DECISION_BONUS_GRADE_S_PLUS, "Grade S+")

        if signal_strength == "ELITE":
            self._add_adjustment(adjustments, Config.DECISION_BONUS_ELITE, "ELITE")

        if signal_confidence >= Config.DECISION_EXCEPTION_MIN_CONFIDENCE:
            self._add_adjustment(adjustments, Config.DECISION_BONUS_CONFIDENCE_95, "Confidence >=95")

        if rr_value is not None:
            if rr_value >= 5:
                self._add_adjustment(adjustments, Config.DECISION_BONUS_RR_5, "RR >=5")
            elif rr_value >= minimum_rr:
                self._add_adjustment(adjustments, Config.DECISION_BONUS_RR_3, "RR >=3")

        if self._is_alignment_bonus(mtf, direction):
            self._add_adjustment(adjustments, Config.DECISION_BONUS_HTF_LTF_ALIGNMENT, "HTF + LTF same direction")

        self._apply_directional_adjustment(adjustments, unicorn, direction, "Unicorn", Config.DECISION_BONUS_UNICORN_ALIGNMENT, Config.DECISION_PENALTY_UNICORN_MISMATCH)
        self._apply_directional_adjustment(adjustments, cisd, direction, "CISD", Config.DECISION_BONUS_CISD_ALIGNMENT, Config.DECISION_PENALTY_CISD_MISMATCH)
        self._apply_directional_adjustment(adjustments, volume_profile, direction, "Volume Profile", Config.DECISION_BONUS_VOLUME_PROFILE_ALIGNMENT, Config.DECISION_PENALTY_VOLUME_PROFILE_MISMATCH)

        if not ote or not ote.get("valid", False):
            self._add_adjustment(adjustments, Config.DECISION_PENALTY_OTE_MISSING, "OTE missing")

        if not htf_orderblock or not htf_orderblock.get("valid", False):
            self._add_adjustment(adjustments, Config.DECISION_PENALTY_HTF_ORDERBLOCK_MISSING, "HTF Order Block missing")

        if not smt or not smt.get("active", False):
            self._add_adjustment(adjustments, Config.DECISION_PENALTY_SMT_MISSING, "SMT missing")

        if not liquidity_sweep or not liquidity_sweep.get("is_sweep", False):
            self._add_adjustment(adjustments, Config.DECISION_PENALTY_LIQUIDITY_SWEEP_MISSING, "Liquidity Sweep missing")

        if not self._has_stack_confluence(confluence):
            self._add_adjustment(adjustments, Config.DECISION_PENALTY_STACK_CONFLUENCE_MISSING, "Stack Confluence missing")

        return adjustments

    def _apply_directional_adjustment(self, adjustments, module, direction, label, bonus, penalty):
        if not module or not isinstance(module, dict) or not module.get("active", False):
            return

        module_direction = self._extract_direction(module)
        if module_direction == "NONE":
            return

        if self._match_direction_raw(module_direction, direction):
            self._add_adjustment(adjustments, bonus, f"{label} same direction")
        else:
            self._add_adjustment(adjustments, penalty, f"{label} mismatch")

    def _is_alignment_bonus(self, mtf, direction):
        if not mtf or not isinstance(mtf, dict):
            return False

        if not mtf.get("valid", False):
            return False

        mtf_direction = mtf.get("entry") or mtf.get("direction")
        if not mtf_direction:
            return False

        return self._match_direction_raw(mtf_direction, direction)

    def _has_stack_confluence(self, confluence):
        if not isinstance(confluence, dict):
            return False

        checks = confluence.get("checks") or []
        return any("✔ Stack Confluence" in str(item) for item in checks)

    def _high_quality_mismatch_override(self, signal_grade, signal_strength, signal_confidence, rr_value, soft_blockers):
        if len(soft_blockers) != Config.DECISION_EXCEPTION_MAX_SOFT_BLOCKERS:
            return False

        if signal_grade not in ["S+", "S"]:
            return False

        if signal_strength != "ELITE":
            return False

        if signal_confidence < Config.DECISION_EXCEPTION_MIN_CONFIDENCE:
            return False

        if rr_value is None or rr_value < Config.DECISION_EXCEPTION_MIN_RR:
            return False

        return any("mismatch" in item["label"].lower() for item in soft_blockers)

    def _build_decision_reason(self, score, bonuses, soft_blockers, critical_blockers, action, override_applies):
        lines = [f"Decision Score: {self._fmt_number(score, force_int=True)}"]

        for item in bonuses:
            lines.append(self._format_adjustment_line(item))

        for item in soft_blockers:
            lines.append(self._format_adjustment_line(item))

        if critical_blockers:
            lines.append("Critical Blockers:")
            for item in critical_blockers:
                lines.append(f"- {item}")

        if override_applies:
            lines.append("Override: high-quality mismatch exception met")

        lines.append(f"Final Action: {action}")
        return "\n".join(lines)

    def _format_adjustment_line(self, item):
        delta = int(item["delta"])
        sign = "+" if delta > 0 else ""
        return f"{sign}{delta} {item['label']}"

    def _add_adjustment(self, adjustments, delta, label):
        if delta == 0:
            return
        adjustments.append({"delta": delta, "label": label})

    def _append_unique(self, items, value):
        if value is not None and value not in items:
            items.append(value)

    def _clamp_score(self, value):
        minimum_score = float(getattr(Config, "DECISION_SCORE_MIN", 0))
        maximum_score = float(getattr(Config, "DECISION_SCORE_MAX", 100))
        return max(minimum_score, min(maximum_score, value))

    def _safe_number(self, value, default=None):
        if isinstance(value, bool):
            return default
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _fmt_number(self, value, force_int=False):
        if value is None:
            return "None"
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return str(value)

        if force_int:
            return str(int(round(numeric_value)))
        if numeric_value.is_integer():
            return str(int(numeric_value))
        return str(round(numeric_value, 2))

    def _normalize_direction(self, signal_dir):
        if signal_dir in ["LONG", "SHORT"]:
            return signal_dir
        return "WAIT"

    def _extract_direction(self, module):
        if not isinstance(module, dict):
            return "NONE"

        for key in ("direction", "signal", "trend", "state_direction"):
            value = module.get(key)
            if value:
                return value

        best = module.get("best")
        if isinstance(best, dict):
            for key in ("direction", "signal", "trend"):
                value = best.get(key)
                if value:
                    return value

        return "NONE"

    def _extract_confidence(self, module):
        if not isinstance(module, dict):
            return 0

        for key in ("confidence", "score", "phase_score", "strength_score"):
            value = module.get(key)
            if isinstance(value, (int, float)):
                return value

        best = module.get("best")
        if isinstance(best, dict):
            for key in ("confidence", "score", "phase_score", "strength_score"):
                value = best.get(key)
                if isinstance(value, (int, float)):
                    return value

        return 0

    def _match_direction(self, module, direction):
        module_direction = self._extract_direction(module)
        return self._match_direction_raw(module_direction, direction)

    def _match_direction_raw(self, module_direction, direction):
        return (
            (module_direction in ["BULLISH", "LONG"] and direction == "LONG")
            or (module_direction in ["BEARISH", "SHORT"] and direction == "SHORT")
        )
