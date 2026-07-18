"""
signal_engine.py
Atlas Signal Engine v2
"""

class SignalEngine:


    def apply_market_phase(self, confidence, market_phase):

        phase = market_phase.get("phase")

        if phase == "EXPANSION":
            confidence += 8

        elif phase == "RETRACEMENT":
            confidence -= 8

        elif phase in ["ACCUMULATION", "DISTRIBUTION"]:
            confidence += 3

        return max(0, min(100, confidence))

    def generate(self, analysis):

        confluence = analysis["confluence"]
        confidence = confluence["score"]
        market_phase = analysis.get("market_phase")

        if market_phase:
            confidence = self.apply_market_phase(confidence, market_phase)

        # Grade
        if confidence >= 90:
            grade = "S+"
            stars = "★★★★★"
            strength = "ELITE"

        elif confidence >= 80:
            grade = "A+"
            stars = "★★★★★"
            strength = "STRONG"

        elif confidence >= 70:
            grade = "A"
            stars = "★★★★☆"
            strength = "GOOD"

        elif confidence >= 60:
            grade = "B"
            stars = "★★★☆☆"
            strength = "NORMAL"

        elif confidence >= 50:
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
            "confidence": confidence,
            "grade": grade,
            "stars": stars,
            "strength": strength,
            "checks": confluence["checks"]
        }
