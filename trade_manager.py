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
        analysis=None,
        journal=None,
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

        trade = {
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

        if journal is not None:
            journal.register_trade(
                trade={
                    "side": signal["signal"],
                    "entry": entry.get("entry"),
                    "stop_loss": entry.get("stop_loss"),
                    "tp1": risk.get("tp1") if risk else None,
                    "tp2": risk.get("tp2") if risk else None,
                    "tp3": risk.get("tp3") if risk else None,
                    "rr": risk.get("rr") if risk else None,
                    "confluence_score": confluence.get("score", 0) if confluence else 0,
                    "confidence": signal.get("confidence", 0),
                },
                analysis=analysis,
            )

        return trade
