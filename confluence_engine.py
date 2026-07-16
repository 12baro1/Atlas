"""
confluence_engine.py
Atlas SMC Engine
"""

class ConfluenceEngine:
    """
    Combines multiple confirmations into a confidence score.
    """

    def evaluate(self, mtf, entry, confirmation,
                 premium_discount=None,
                 liquidity=None,
                 killzone=None):

        score = 0
        reasons = []

        if mtf and mtf.get("valid"):
            score += 30
            reasons.append("MTF aligned")

        if entry and entry.get("valid"):
            score += 20
            reasons.append("Entry valid")

        if confirmation and confirmation.get("confirmed"):
            score += 20
            reasons.append("Entry confirmed")

        if premium_discount:
            zone = premium_discount.get("zone")
            direction = mtf.get("entry") if mtf else None

            if direction == "LONG" and zone == "DISCOUNT":
                score += 15
                reasons.append("Discount zone")

            elif direction == "SHORT" and zone == "PREMIUM":
                score += 15
                reasons.append("Premium zone")

        if liquidity:
            if liquidity.get("buy_side") or liquidity.get("sell_side"):
                score += 10
                reasons.append("Liquidity sweep")

        if killzone and killzone.get("active"):
            score += 5
            reasons.append("Kill Zone")

        return {
            "score": min(score, 100),
            "confidence": min(score, 100),
            "reasons": reasons
        }
