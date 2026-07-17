"""
trade_manager.py
Atlas SMC Engine v2
"""

class TradeManager:

    def build(
        self,
        signal,
        entry,
        confirmation,
        confluence=None,
        risk=None,
    ):

        score = 0
        reasons = []

        # Signal
        if signal["signal"] != "NONE":
            score += 20
            reasons.append("Signal")

        # Entry
        if entry["valid"]:
            score += 20
            reasons.append("Entry")

        # Confirmation
        if confirmation["confirmed"]:
            score += 20
            reasons.append("Confirmation")

        # Confluence
        if confluence:

            c = confluence.get("confidence", 0)

            score += int(c * 0.30)

            if c > 0:
                reasons.append("Confluence")

        # Risk
        if risk is not None:
            score += 10
            reasons.append("Risk")

        score = min(score, 100)

        if score >= 90:
            stars = "★★★★★"
            grade = "A+"

        elif score >= 80:
            stars = "★★★★☆"
            grade = "A"

        elif score >= 70:
            stars = "★★★☆☆"
            grade = "B"

        elif score >= 60:
            stars = "★★☆☆☆"
            grade = "C"

        else:
            stars = "★☆☆☆☆"
            grade = "D"

        return {
            "valid": entry["valid"],
            "score": score,
            "grade": grade,
            "stars": stars,
            "direction": signal["signal"],
            "reasons": reasons,
            "entry": entry,
            "confirmation": confirmation,
            "risk": risk,
        }
