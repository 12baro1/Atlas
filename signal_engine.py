"""
signal_engine.py
Atlas Signal Engine v2
"""


class SignalEngine:

    def generate(self, analysis):

        confluence = analysis["confluence"]

        confidence = confluence["score"]

        if confidence >= 90:
            grade = "A+"
            stars = "★★★★★"
            strength = "ELITE"

        elif confidence >= 80:
            grade = "A"
            stars = "★★★★★"
            strength = "STRONG"

        elif confidence >= 70:
            grade = "B"
            stars = "★★★★☆"
            strength = "GOOD"

        elif confidence >= 60:
            grade = "C"
            stars = "★★★☆☆"
            strength = "NORMAL"

        elif confidence >= 45:
            grade = "D"
            stars = "★★☆☆☆"
            strength = "WEAK"

        else:
            grade = "F"
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
