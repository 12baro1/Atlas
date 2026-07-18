"""
signal_engine.py
Atlas Signal Engine v3
Market phase aware signal generation
"""

class SignalEngine:

    def generate(self, analysis):

        confluence = analysis["confluence"]
        confidence = confluence["score"]
        
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
