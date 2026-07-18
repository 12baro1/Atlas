"""
signal_engine.py
Atlas Signal Engine v3
Market phase aware signal generation
"""

class SignalEngine:

    def generate(self, analysis):

        confluence = analysis["confluence"]
        confidence = confluence["score"]

        liquidity_sweep = analysis.get("liquidity_sweep", {})
        smt = analysis.get("smt", {})
        unicorn = analysis.get("unicorn", {})
        cisd = analysis.get("cisd", {})
        
        # Market phase adjustment
        market_phase = analysis.get("market_phase", {})
        phase_name = market_phase.get("phase", "Ranging")
        phase_confidence = market_phase.get("phase_confidence", 0)
        phase_score = market_phase.get("phase_score", 0)
        
        # Adjust confidence based on phase
        confidence_adjusted = self._adjust_confidence_by_phase(
            base_confidence=confidence,
            phase=phase_name,
            phase_score=phase_score,
            mtf_alignment=market_phase.get("mtf_alignment", 0)
        )

        confidence_adjusted = self._adjust_confidence_by_liquidity_and_smt(
            base_confidence=confidence_adjusted,
            liquidity_sweep=liquidity_sweep,
            smt=smt,
            unicorn=unicorn,
            cisd=cisd,
        )

        # Grade
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

        direction = analysis["entry"]["direction"]

        if direction not in ["LONG", "SHORT"]:
            direction = "WAIT"

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
        }

    def _adjust_confidence_by_phase(self, base_confidence, phase, phase_score, mtf_alignment):
        """Adjust signal confidence based on market phase quality."""
        
        # Phase quality bonus/penalty
        phase_adjustment = {
            "Expansion": 10,      # Best for trading
            "Trending": 8,        # Good for trading
            "Accumulation": 5,    # Setup phase
            "Distribution": -10,  # Avoid
            "Consolidation": -5,  # Risky
            "Manipulation": -15,  # Trap risk
            "Reversal": 3,        # Caution
            "Ranging": -8,        # Choppy
        }
        
        adjustment = phase_adjustment.get(phase, 0)
        
        # MTF alignment bonus
        if mtf_alignment >= 100:
            adjustment += 5
        elif mtf_alignment >= 75:
            adjustment += 3
        
        # Phase score contribution
        adjustment += (phase_score / 100) * 5
        
        adjusted = base_confidence + adjustment
        return max(0, min(100, adjusted))

    def _adjust_confidence_by_liquidity_and_smt(self, base_confidence, liquidity_sweep, smt, unicorn, cisd):
        """Sweep, SMT, Unicorn ve CISD kalitesine göre güven puanını günceller."""
        adjusted = base_confidence

        if liquidity_sweep.get("is_sweep"):
            adjusted += min(10, liquidity_sweep.get("strength_score", 0) / 10)
            if liquidity_sweep.get("post_structure", {}).get("confirmed"):
                adjusted += 4

        if smt.get("active"):
            adjusted += min(8, smt.get("confidence", 0) / 12)

        if unicorn.get("active"):
            adjusted += min(10, unicorn.get("confidence", 0) / 10)

            best = unicorn.get("best") or {}
            direction = best.get("direction")
            if direction == "BULLISH":
                adjusted += 2
            elif direction == "BEARISH":
                adjusted += 2

        if cisd.get("active"):
            adjusted += min(9, cisd.get("confidence", 0) / 11)

            cisd_direction = cisd.get("direction")
            if cisd_direction in ["BULLISH", "BEARISH"]:
                adjusted += 1

        return max(0, min(100, adjusted))
