"""
decision_engine.py
Atlas Decision Engine v2
"""

from config import Config


class DecisionEngine:
    """Atlas içindeki tüm modülleri birleştirerek nihai işlem kararını üretir."""

    REQUIRED_SIGNAL_THRESHOLD = 75
    REQUIRED_CONFLUENCE_THRESHOLD = 70
    OPEN_SCORE_THRESHOLD = 72
    AVOID_SCORE_THRESHOLD = 40

    def decide(self, analysis=None, **kwargs):
        """Bundle tabanlı karar üretir; eski kwargs tabanlı çağrıları da destekler."""
        context = self._normalize_context(analysis, kwargs)

        signal = context["signal"]
        confluence = context["confluence"]
        entry = context["entry"]
        risk = context["risk"]
        cisd = context["cisd"]
        volume_profile = context["volume_profile"]
        institutional = context["institutional"]
        unicorn = context["unicorn"]
        smt = context["smt"]
        market_phase = context["market_phase"]
        liquidity_sweep = context["liquidity_sweep"]
        modules = context["modules"]

        signal_dir = signal.get("signal", "WAIT")
        signal_confidence = signal.get("confidence", 0)
        confluence_score = confluence.get("score", 0)
        entry_valid = bool(entry.get("valid", False))
        risk_valid = self._is_risk_valid(risk)
        rr_value = risk.get("rr") if isinstance(risk, dict) else None
        minimum_rr = getattr(Config, "MINIMUM_RR", 2.0)

        module_scores = {}
        reasons = []
        blockers = []

        direction = self._normalize_direction(signal_dir)
        if direction == "WAIT":
            blockers.append("Signal direction is not actionable")

        core_score = 0
        core_score += self._score_signal(signal_confidence, direction)
        core_score += self._score_confluence(confluence_score)
        core_score += self._score_entry(entry_valid)
        core_score += self._score_risk(risk)
        core_score += self._score_market_phase(market_phase, direction)
        core_score += self._score_liquidity_sweep(liquidity_sweep, direction)
        core_score += self._score_alignment_gate(cisd, direction)
        core_score += self._score_alignment_gate(volume_profile, direction)
        core_score += self._score_alignment_gate(institutional, direction)
        core_score += self._score_alignment_gate(unicorn, direction)
        core_score += self._score_alignment_gate(smt, direction)

        generic_score, generic_reasons, generic_blockers = self._score_modules(modules, direction)
        module_scores["generic"] = generic_score
        if generic_reasons:
            reasons.extend(generic_reasons)
        if generic_blockers:
            blockers.extend(generic_blockers)

        total_score = max(0, min(100, core_score + generic_score))

        if signal_dir in ["LONG", "SHORT"] and signal_confidence < self.REQUIRED_SIGNAL_THRESHOLD:
            blockers.append(f"Signal confidence below threshold: {signal_confidence}")
        if confluence_score < self.REQUIRED_CONFLUENCE_THRESHOLD:
            blockers.append(f"Confluence score below threshold: {confluence_score}")
        if not entry_valid:
            blockers.append("Entry is not valid")
        if not risk_valid:
            blockers.append("Risk is not valid")
        if rr_value is None:
            blockers.append("RR is missing")
        elif rr_value < minimum_rr:
            blockers.append(f"RR below threshold: {rr_value} < {minimum_rr}")

        action = "WAIT"
        mismatch_detected = self._has_direction_conflict(cisd, volume_profile, institutional, unicorn, smt, direction)

        if mismatch_detected:
            blockers.append("Directional mismatch detected")

        hard_blocked = (not entry_valid) or (not risk_valid) or (rr_value is None) or (rr_value < minimum_rr)

        if blockers and total_score < self.AVOID_SCORE_THRESHOLD:
            action = "AVOID"
        elif hard_blocked and direction in ["LONG", "SHORT"]:
            action = "WAIT"
        elif direction in ["LONG", "SHORT"] and total_score >= self.OPEN_SCORE_THRESHOLD and not mismatch_detected:
            action = direction
        elif direction in ["LONG", "SHORT"]:
            action = "WAIT"

        reason = self._build_reason(
            action=action,
            total_score=total_score,
            signal_dir=signal_dir,
            blockers=blockers,
            reasons=reasons,
            confluence_score=confluence_score,
            signal_confidence=signal_confidence,
        )

        return {
            "action": action,
            "reason": reason,
            "signal": signal_dir,
            "confidence": signal_confidence,
            "score": total_score,
            "confluence_score": confluence_score,
            "entry_valid": entry_valid,
            "risk_valid": risk_valid,
            "rr": rr_value,
            "minimum_rr": minimum_rr,
            "cisd_active": bool(cisd.get("active", False)),
            "cisd_direction": cisd.get("direction", "NONE"),
            "cisd_match": self._match_direction(cisd, direction),
            "volume_profile_active": bool(volume_profile.get("active", False)),
            "volume_profile_direction": volume_profile.get("direction", "NONE"),
            "volume_profile_match": self._match_direction(volume_profile, direction),
            "institutional_active": bool(institutional.get("active", False)),
            "institutional_direction": institutional.get("direction", "NONE"),
            "institutional_match": self._match_direction(institutional, direction),
            "unicorn_active": bool(unicorn.get("active", False)),
            "unicorn_direction": unicorn.get("direction", unicorn.get("best", {}).get("direction", "NONE")),
            "smt_active": bool(smt.get("active", False)),
            "smt_direction": smt.get("direction", "NONE"),
            "market_phase": market_phase.get("phase", "Ranging"),
            "liquidity_sweep_strength": liquidity_sweep.get("strength_score", 0),
            "module_scores": module_scores,
            "blockers": blockers,
            "reasons": reasons,
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
        market_phase = bundle.get("market_phase") or {}
        liquidity_sweep = bundle.get("liquidity_sweep") or {}

        modules = bundle.get("modules") or self._discover_modules(bundle)

        return {
            "signal": signal,
            "confluence": confluence,
            "entry": entry,
            "risk": risk,
            "cisd": cisd,
            "volume_profile": volume_profile,
            "institutional": institutional,
            "unicorn": unicorn,
            "smt": smt,
            "market_phase": market_phase,
            "liquidity_sweep": liquidity_sweep,
            "modules": modules,
        }

    def _discover_modules(self, bundle):
        """Future modules için üst seviye dict alanlarını otomatik toplar."""
        ignored = {
            "signal",
            "confluence",
            "entry",
            "risk",
            "cisd",
            "volume_profile",
            "unicorn",
            "smt",
            "market_phase",
            "liquidity_sweep",
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

    def _score_signal(self, confidence, direction):
        if direction not in ["LONG", "SHORT"]:
            return -12
        return 18 + min(12, int(confidence / 7))

    def _score_confluence(self, score):
        return min(22, int(score / 4))

    def _score_entry(self, valid):
        return 10 if valid else -14

    def _score_risk(self, risk):
        if risk is None:
            return -16

        rr = risk.get("rr")
        if rr is None:
            rr = risk.get("risk")
        if rr is None:
            return -10

        score = 8
        if rr >= 5:
            score += 12
        elif rr >= 3:
            score += 9
        elif rr >= 2:
            score += 5
        else:
            score -= 4

        position_size = risk.get("position_size")
        if position_size is not None and position_size > 0:
            score += 2

        return score

    def _is_risk_valid(self, risk):
        if risk is None:
            return False
        if risk.get("rr") is not None:
            entry = risk.get("entry")
            stop_loss = risk.get("stop_loss")
            return entry is not None and stop_loss is not None
        if risk.get("risk") is not None:
            return True
        return False

    def _score_market_phase(self, market_phase, direction):
        phase = market_phase.get("phase", "Ranging")
        strength = market_phase.get("phase_score", 0)

        phase_bonus = {
            "Expansion": 8,
            "Trending": 7,
            "Accumulation": 4,
            "Distribution": -6,
            "Consolidation": -4,
            "Manipulation": -10,
            "Reversal": 5,
            "Ranging": -5,
        }.get(phase, 0)

        if direction == "LONG" and phase in ["Expansion", "Trending", "Accumulation", "Reversal"]:
            phase_bonus += 2
        elif direction == "SHORT" and phase in ["Expansion", "Trending", "Distribution", "Reversal"]:
            phase_bonus += 2

        return phase_bonus + min(4, int(strength / 25))

    def _score_liquidity_sweep(self, liquidity_sweep, direction):
        if not liquidity_sweep.get("is_sweep"):
            if liquidity_sweep.get("is_breakout"):
                return -6
            return 0

        score = 8 + min(8, int(liquidity_sweep.get("strength_score", 0) / 10))
        post_structure = liquidity_sweep.get("post_structure", {})
        if post_structure.get("confirmed"):
            score += 4
        if direction == "LONG" and liquidity_sweep.get("sell_side"):
            score += 2
        elif direction == "SHORT" and liquidity_sweep.get("buy_side"):
            score += 2
        return score

    def _score_alignment_gate(self, module, direction):
        if not module or not isinstance(module, dict):
            return 0

        if not module.get("active"):
            return 0

        module_direction = self._extract_direction(module)
        confidence = self._extract_confidence(module)
        score = 4 + min(8, int(confidence / 12))

        if module_direction == "NONE":
            return score

        if self._match_direction_raw(module_direction, direction):
            return score + 4

        return -6

    def _score_modules(self, modules, direction):
        total = 0
        reasons = []
        blockers = []

        for name, module in modules.items():
            if not isinstance(module, dict):
                continue

            module_score = 0
            if module.get("active") or module.get("valid"):
                module_score += 4

            confidence = self._extract_confidence(module)
            module_score += min(6, int(confidence / 15))

            module_direction = self._extract_direction(module)
            if module_direction != "NONE":
                if self._match_direction_raw(module_direction, direction):
                    module_score += 3
                elif direction in ["LONG", "SHORT"]:
                    module_score -= 4

            if module.get("state") in ["DISCOUNT", "VALUE_LOW", "BELOW_POC"] and direction == "LONG":
                module_score += 2
            if module.get("state") in ["PREMIUM", "VALUE_HIGH", "ABOVE_POC"] and direction == "SHORT":
                module_score += 2

            total += module_score

            if module_score > 0:
                reasons.append(f"{name}: +{module_score}")
            elif module_score < 0:
                blockers.append(f"{name}: {module_score}")

        return total, reasons, blockers

    def _extract_direction(self, module):
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

    def _has_direction_conflict(self, cisd, volume_profile, institutional, unicorn, smt, direction):
        modules = [cisd, volume_profile, institutional, unicorn, smt]
        for module in modules:
            if not isinstance(module, dict) or not module.get("active"):
                continue

            if self._match_direction(module, direction) is False:
                return True

        return False

    def _normalize_direction(self, signal_dir):
        if signal_dir in ["LONG", "SHORT"]:
            return signal_dir
        return "WAIT"

    def _build_reason(self, action, total_score, signal_dir, blockers, reasons, confluence_score, signal_confidence):
        parts = [f"Action={action}", f"Score={total_score}", f"Signal={signal_dir}", f"Confidence={signal_confidence}", f"Confluence={confluence_score}"]
        if blockers:
            parts.append("Blockers=" + "; ".join(blockers[:4]))
        if reasons:
            parts.append("Drivers=" + "; ".join(reasons[:4]))
        return " | ".join(parts)
