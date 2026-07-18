"""
signal_engine.py
Atlas Signal Engine v4
Market phase aware signal generation.
"""

from core.analysis_utils import clamp, direction_matches, extract_confidence, extract_direction, is_active, normalize_direction


class SignalEngine:

    def generate(self, analysis):
        confluence = analysis["confluence"]
        base_confidence = confluence["score"]

        liquidity_sweep = analysis.get("liquidity_sweep", {})
        smt = analysis.get("smt", {})
        unicorn = analysis.get("unicorn", {})
        cisd = analysis.get("cisd", {})
        volume_profile = analysis.get("volume_profile", {})

        market_phase = analysis.get("market_phase", {})
        phase_name = market_phase.get("phase", "Ranging")
        phase_confidence = market_phase.get("phase_confidence", 0)
        phase_score = market_phase.get("phase_score", 0)
        mtf_alignment = market_phase.get("mtf_alignment", 0)

        direction = normalize_direction(analysis["entry"].get("direction"), default="WAIT")

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
        )

        confidence_adjusted = clamp(confidence_adjusted)

        if confidence_adjusted >= 90:
            grade = "S+"
            stars = "★★★★★"
            strength = "ELITE"
        elif confidence_adjusted >= 80:
            grade = "A+"
            stars = "★★★★★"
            strength = "STRONG"
        elif confidence_adjusted >= 70:
            grade = "A"
            stars = "★★★★☆"
            strength = "GOOD"
        elif confidence_adjusted >= 60:
            grade = "B"
            stars = "★★★☆☆"
            strength = "NORMAL"
        elif confidence_adjusted >= 50:
            grade = "C"
            stars = "★★☆☆☆"
            strength = "WEAK"
        else:
            grade = "D"
            stars = "★☆☆☆☆"
            strength = "VERY WEAK"

        return {
            "signal": direction,
            "confidence": int(confidence_adjusted),
            "grade": grade,
            "stars": stars,
            "strength": strength,
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
            "alignment_conflicts": self._alignment_conflicts(direction, liquidity_sweep, smt, unicorn, cisd, volume_profile),
        }

    def _adjust_confidence_by_phase(self, base_confidence, phase, phase_score, mtf_alignment):
        """Adjust signal confidence based on market phase quality."""
        phase_adjustment = {
            "Expansion": 10,
            "Trending": 8,
            "Accumulation": 5,
            "Distribution": -12,
            "Consolidation": -5,
            "Manipulation": -15,
            "Reversal": 4,
            "Ranging": -8,
        }

        adjustment = phase_adjustment.get(phase, 0)

        if mtf_alignment >= 100:
            adjustment += 5
        elif mtf_alignment >= 75:
            adjustment += 3

        adjustment += (phase_score / 100) * 5

        adjusted = base_confidence + adjustment
        return clamp(adjusted)

    def _adjust_confidence_by_liquidity_and_smt(self, base_confidence, signal_direction, liquidity_sweep, smt, unicorn, cisd, volume_profile):
        """Sweep, SMT, Unicorn, CISD ve Volume Profile kalitesine göre güven puanını günceller."""
        adjusted = base_confidence
        active_modules = [liquidity_sweep, smt, unicorn, cisd, volume_profile]

        if liquidity_sweep.get("is_sweep"):
            adjusted += min(10, liquidity_sweep.get("strength_score", 0) / 10)
            if liquidity_sweep.get("post_structure", {}).get("confirmed"):
                adjusted += 4

        if is_active(smt):
            adjusted += min(8, extract_confidence(smt) / 12)

        if is_active(unicorn):
            adjusted += min(10, extract_confidence(unicorn) / 10)
            best_direction = extract_direction(unicorn)
            if direction_matches(best_direction, signal_direction):
                adjusted += 2

        if is_active(cisd):
            adjusted += min(9, extract_confidence(cisd) / 11)
            if direction_matches(extract_direction(cisd), signal_direction):
                adjusted += 2

        if is_active(volume_profile):
            adjusted += min(8, extract_confidence(volume_profile) / 12)

        adjusted -= self._alignment_conflicts(signal_direction, *active_modules)

        return clamp(adjusted)

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
