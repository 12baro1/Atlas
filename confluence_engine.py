"""
confluence_engine.py
Atlas Confluence Engine v4
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
        breaker,
        killzone,
        session
    ):

        score = 0
        checks = []

        # MTF
        if mtf["valid"]:
            score += 20
            checks.append("✓ MTF Alignment")
        else:
            checks.append("✗ MTF")

        # Trend
        trend_name = trend["trend"]

        if trend_name == "BULLISH" and entry["direction"] == "LONG":
            score += 15
            checks.append("✓ Bullish Trend")

        elif trend_name == "BEARISH" and entry["direction"] == "SHORT":
            score += 15
            checks.append("✓ Bearish Trend")

        else:
            checks.append("✗ Trend")

        # Entry
        if entry["valid"]:
            score += 20
            checks.append("✓ Entry")

        else:
            checks.append("✗ Entry")

        # Confirmation
        if confirmation["confirmed"]:
            score += 15
            checks.append("✓ Confirmation")

        else:
            checks.append("✗ Confirmation")

        # Premium / Discount
        zone = premium_discount["zone"]

        if entry["direction"] == "LONG":

            if zone == "DISCOUNT":
                score += 10
                checks.append("✓ Discount")

            else:
                checks.append("✗ Premium")

        elif entry["direction"] == "SHORT":

            if zone == "PREMIUM":
                score += 10
                checks.append("✓ Premium")

            else:
                checks.append("✗ Discount")

        # Liquidity Sweep
        if liquidity_sweep:
            score += 10
            checks.append("✓ Liquidity Sweep")

        else:
            checks.append("✗ No Sweep")

        # -----------------
        # Breaker Block
        # -----------------

       if breaker:

           score += 10
           checks.append("✓ Breaker Block")

       else:

           checks.append("✗ Breaker Block")

        # Killzone
        if killzone:
            score += 5
            checks.append("✓ Killzone")

        else:
            checks.append("✗ Killzone")

        # Session
        if session:
            score += 5
            checks.append("✓ Session")

        else:
            checks.append("✗ Session")

        confidence = min(score, 100)

        return {
            "confidence": confidence,
            "score": score,
            "checks": checks
        }
