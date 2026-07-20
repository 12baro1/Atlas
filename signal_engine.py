"""
signal_engine.py
Atlas Signal Engine v4
Market phase aware signal generation.
"""

import logging

from core.analysis_utils import clamp, direction_matches, extract_confidence, extract_direction, is_active, normalize_direction


class SignalEngine:

    def __init__(self):
        self.logger = logging.getLogger("atlas.signal")

    def generate(self, analysis):
        confluence = analysis["confluence"]
        base_confidence = self._normalize_confluence_score(confluence.get("score", 0))

        liquidity_sweep = analysis.get("liquidity_sweep", {})
        smt = analysis.get("smt", {})
        unicorn = analysis.get("unicorn", {})
        cisd = analysis.get("cisd", {})
        volume_profile = analysis.get("volume_profile", {})
        institutional = analysis.get("institutional", {})

        market_phase = analysis.get("market_phase", {})
        phase_name = market_phase.get("phase", "Ranging")
        phase_confidence = market_phase.get("phase_confidence", 0)
        phase_score = market_phase.get("phase_score", 0)
        mtf_alignment = market_phase.get("mtf_alignment", 0)

        entry = analysis.get("entry", {})
        confirmation = analysis.get("confirmation", {})
        inferred_entry_valid = normalize_direction(entry.get("direction"), default="WAIT") in {"LONG", "SHORT"}
        entry_valid = bool(entry.get("valid", inferred_entry_valid))
        confirmed = bool(confirmation.get("confirmed", True))

        direction, signal_reason, wait_reason = self._resolve_signal_direction(
            raw_direction=entry.get("direction"),
            entry_valid=entry_valid,
            confirmed=confirmed,
        )

        confidence_adjusted = self._adjust_confidence_by_phase(
            base_confidence=base_confidence,
            phase=phase_name,
            phase_score=phase_score,
            mtf_alignment=mtf_alignment,
        )

        confidence_adjusted = self._adjust_confidence_by_liquidity_and_smt(
            base_confidence=confidence_adjusted,
            signal_direction=direction,
            liquidity_sweep=liquidity_sweep,
            smt=smt,
            unicorn=unicorn,
            cisd=cisd,
            volume_profile=volume_profile,
            institutional=institutional,
        )

        confidence_adjusted = clamp(confidence_adjusted)

        if confidence_adjusted >= 96:
            grade = "S+"
            stars = "★★★★★"
            strength = "ELITE"
        elif confidence_adjusted >= 90:
            grade = "A+"
            stars = "★★★★★"
            strength = "STRONG"
        elif confidence_adjusted >= 82:
            grade = "A"
            stars = "★★★★☆"
            strength = "GOOD"
        elif confidence_adjusted >= 72:
            grade = "B"
            stars = "★★★☆☆"
            strength = "NORMAL"
        elif confidence_adjusted >= 55:
            grade = "C"
            stars = "★★☆☆☆"
            strength = "WEAK"
        else:
            grade = "D"
            stars = "★☆☆☆☆"
            strength = "VERY WEAK"

        payload = {
            "signal": direction,
            "confidence": int(confidence_adjusted),
            "grade": grade,
            "stars": stars,
            "strength": strength,
            "signal_reason": signal_reason,
            "wait_reason": wait_reason,
            "checks": confluence["checks"],
            "market_phase": phase_name,
            "phase_quality": phase_confidence,
            "liquidity_strength": liquidity_sweep.get("strength_score", 0),
            "smt_confidence": smt.get("confidence", 0),
            "unicorn_confidence": unicorn.get("confidence", 0),
            "unicorn_active": unicorn.get("active", False),
            "cisd_confidence": cisd.get("confidence", 0),
            "cisd_active": cisd.get("active", False),
            "cisd_direction": cisd.get("direction", "NONE"),
            "volume_profile_confidence": volume_profile.get("confidence", 0),
            "volume_profile_direction": volume_profile.get("direction", "NONE"),
            "institutional_confidence": institutional.get("confidence", 0),
            "institutional_direction": institutional.get("direction", "NONE"),
            "alignment_conflicts": self._alignment_conflicts(direction, liquidity_sweep, smt, unicorn, cisd, volume_profile),
        }

        if direction == "WAIT":
            self.logger.info(
                "Signal WAIT | reason=%s entry_valid=%s confirmed=%s raw_direction=%s",
                wait_reason,
                entry_valid,
                confirmed,
                entry.get("direction"),
            )
        else:
            self.logger.info(
                "Signal %s | reason=%s confidence=%s grade=%s",
                direction,
                signal_reason,
                payload["confidence"],
                grade,
            )

        return payload

    def _resolve_signal_direction(self, raw_direction, entry_valid, confirmed):
        normalized = normalize_direction(raw_direction, default="WAIT")

        if not entry_valid:
            return "WAIT", "Entry invalid", "entry_invalid"

        if not confirmed:
            return "WAIT", "Entry not confirmed", "entry_not_confirmed"

        if normalized in {"LONG", "SHORT"}:
            return normalized, "Entry valid and confirmed", None

        return "WAIT", "Direction unresolved", "direction_unresolved"

    def _adjust_confidence_by_phase(self, base_confidence, phase, phase_score, mtf_alignment):
        """Adjust signal confidence based on market phase quality."""
        phase_adjustment = {
            "Expansion": 4,
            "Trending": 3,
            "Accumulation": 1,
            "Distribution": -8,
            "Consolidation": -3,
            "Manipulation": -10,
            "Reversal": 2,
            "Ranging": -5,
        }

        adjustment = phase_adjustment.get(phase, 0)

        if mtf_alignment >= 100:
            adjustment += 2
        elif mtf_alignment >= 75:
            adjustment += 1

        adjustment += (phase_score / 100) * 2

        adjusted = base_confidence + adjustment
        return clamp(adjusted)

    def _adjust_confidence_by_liquidity_and_smt(self, base_confidence, signal_direction, liquidity_sweep, smt, unicorn, cisd, volume_profile, institutional):
        """Sweep, SMT, Unicorn, CISD ve Volume Profile kalitesine göre güven puanını günceller."""
        adjusted = base_confidence
        active_modules = [liquidity_sweep, smt, unicorn, cisd, volume_profile, institutional]
        raw_delta = 0.0

        if liquidity_sweep.get("is_sweep"):
            raw_delta += min(5, liquidity_sweep.get("strength_score", 0) / 20)
            if liquidity_sweep.get("post_structure", {}).get("confirmed"):
                raw_delta += 2

        if is_active(smt):
            raw_delta += min(4, extract_confidence(smt) / 25)

        if is_active(unicorn):
            raw_delta += min(5, extract_confidence(unicorn) / 20)
            best_direction = extract_direction(unicorn)
            if direction_matches(best_direction, signal_direction):
                raw_delta += 1

        if is_active(cisd):
            raw_delta += min(4, extract_confidence(cisd) / 22)
            if direction_matches(extract_direction(cisd), signal_direction):
                raw_delta += 1

        if is_active(volume_profile):
            raw_delta += min(3, extract_confidence(volume_profile) / 30)

        if is_active(institutional):
            raw_delta += min(6, extract_confidence(institutional) / 15)
            institutional_direction = extract_direction(institutional)
            if direction_matches(institutional_direction, signal_direction):
                raw_delta += 2
            if institutional.get("execution_quality", {}).get("score", 0) >= 70:
                raw_delta += 1
            if institutional.get("macro_filter", {}).get("active") and institutional.get("macro_filter", {}).get("confidence", 100) < 50:
                raw_delta -= 4
            if institutional.get("news_filter", {}).get("active") and institutional.get("news_filter", {}).get("confidence", 100) < 50:
                raw_delta -= 3

        raw_delta -= self._alignment_conflicts(signal_direction, *active_modules)

        # Modül etkisini yarıya yakın ölçekleyerek grade enflasyonunu düşürür.
        adjusted += raw_delta * 0.6

        return clamp(adjusted)

    def _normalize_confluence_score(self, raw_score):
        """Confluence skorunu 0-100 confidence aralığına kalibre eder."""
        score = float(raw_score or 0)

        if score <= 60:
            normalized = score * 0.9
        elif score <= 100:
            normalized = 54 + ((score - 60) * 0.75)
        elif score <= 140:
            normalized = 84 + ((score - 100) * 0.30)
        elif score <= 180:
            normalized = 96 + ((score - 140) * 0.10)
        else:
            normalized = 100

        return clamp(normalized, 0, 100)

    def _alignment_conflicts(self, signal_direction, *modules):
        if signal_direction not in ["LONG", "SHORT"]:
            return 0

        penalty = 0
        for module in modules:
            if not is_active(module):
                continue

            module_direction = extract_direction(module)
            if module_direction in ["LONG", "SHORT"] and not direction_matches(module_direction, signal_direction):
                penalty += 4 + min(6, int(extract_confidence(module) / 20))

        return penalty
