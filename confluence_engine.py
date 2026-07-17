"""
confluence_engine.py
Atlas SMC Engine v2
"""

class ConfluenceEngine:

    def evaluate(
        self,
        mtf,
        trend,
        entry,
        confirmation,
        premium_discount,
        liquidity_sweep,
        killzone,
        session,
    ):

        score = 0
        checks = []

        # -------------------
        # MTF
        # -------------------

        if mtf.get("valid", False):
            score += 20
            checks.append("✓ Multi Timeframe")
        else:
            checks.append("✗ Multi Timeframe")

        # -------------------
        # Trend
        # -------------------

        if trend == entry["direction"]:
            score += 15
            checks.append("✓ Trend")
        else:
            checks.append("✗ Trend")

        # -------------------
        # Entry
        # -------------------

        if entry["valid"]:
            score += 15
            checks.append("✓ Entry")
        else:
            checks.append("✗ Entry")

        # -------------------
        # Confirmation
        # -------------------

        if confirmation["confirmed"]:
            score += 15
            checks.append("✓ Confirmation")
        else:
            checks.append("✗ Confirmation")

        # -------------------
        # Premium / Discount
        # -------------------

        if entry["direction"] == "LONG":

            if premium_discount["discount"]:
                score += 10
                checks.append("✓ Discount Zone")
            else:
                checks.append("✗ Discount Zone")

        elif entry["direction"] == "SHORT":

            if premium_discount["premium"]:
                score += 10
                checks.append("✓ Premium Zone")
            else:
                checks.append("✗ Premium Zone")

        # -------------------
        # Liquidity Sweep
        # -------------------

        if len(liquidity_sweep) > 0:
            score += 10
            checks.append("✓ Liquidity Sweep")
        else:
            checks.append("✗ Liquidity Sweep")

        # -------------------
        # Kill Zone
        # -------------------

        if killzone["active"]:
            score += 10
            checks.append("✓ Kill Zone")
        else:
            checks.append("✗ Kill Zone")

        # -------------------
        # Session
        # -------------------

        if session["active"]:
            score += 5
            checks.append("✓ Session")
        else:
            checks.append("✗ Session")

        score = min(score, 100)

        return {
            "confidence": score,
            "checks": checks,
            "grade": self.grade(score)
        }

    def grade(self, score):

        if score >= 90:
            return "A+"

        if score >= 80:
            return "A"

        if score >= 70:
            return "B"

        if score >= 60:
            return "C"

        return "D"
