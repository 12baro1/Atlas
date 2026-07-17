"""
signal_engine.py
Atlas SMC Engine v2
"""

class SignalEngine:

    def generate(self, analysis):

        confluence = analysis["confluence"]

        confidence = confluence["confidence"]

        signal = analysis["mtf"]["entry"]

        if signal not in ["LONG", "SHORT"]:
            signal = "NONE"

        if confidence >= 90:
            stars = "★★★★★"
            grade = "A+"

        elif confidence >= 80:
            stars = "★★★★☆"
            grade = "A"

        elif confidence >= 70:
            stars = "★★★☆☆"
            grade = "B"

        elif confidence >= 60:
            stars = "★★☆☆☆"
            grade = "C"

        else:
            stars = "★☆☆☆☆"
            grade = "D"

        strength = self.strength(confidence)

        return {
            "signal": signal,
            "confidence": confidence,
            "grade": grade,
            "stars": stars,
            "strength": strength,
            "checks": confluence["checks"]
        }

    def strength(self, confidence):

        if confidence >= 90:
            return "VERY STRONG"

        if confidence >= 80:
            return "STRONG"

        if confidence >= 70:
            return "GOOD"

        if confidence >= 60:
            return "NORMAL"

        if confidence >= 40:
            return "WEAK"

        return "VERY WEAK"
