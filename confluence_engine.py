"""
confluence_engine.py
Atlas Confluence Engine v2
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
        ote,
        htf_orderblock,
        killzone,
        session,
        breaker=None
    ):

        score = 0
        checks = []

        # Multi Timeframe
        if mtf["valid"]:
            score += 15
            checks.append("✔ Multi Timeframe")
        else:
            checks.append("✘ Multi Timeframe")

        # Trend
        trend_ok = (
            (trend["trend"] == "BULLISH" and entry["direction"] == "LONG") or
            (trend["trend"] == "BEARISH" and entry["direction"] == "SHORT")
        )

        if trend_ok:
            score += 10
            checks.append("✔ Trend")
        else:
            checks.append("✘ Trend")

        # Entry
        if entry["valid"]:
            score += 20
            checks.append("✔ Entry")
        else:
            checks.append("✘ Entry")

        # Confirmation
        if confirmation["confirmed"]:
            score += 15
            checks.append("✔ Confirmation")
        else:
            checks.append("✘ Confirmation")

        # Premium / Discount
        if premium_discount["valid"]:
            score += 10
            checks.append("✔ Premium Zone")
        else:
            checks.append("✘ Premium Zone")

        # Liquidity Sweep
        if liquidity_sweep:
            score += 10
            checks.append("✔ Liquidity Sweep")
        else:
            checks.append("✘ Liquidity Sweep")

        # OTE
        if ote["valid"]:
            score += 10
            checks.append("✔ OTE")
        else:
            checks.append("✘ OTE")

        # Breaker
        if breaker is not None and len(breaker) > 0:
            score += 5
            checks.append("✔ Breaker Block")
        else:
            checks.append("✘ Breaker Block")

        # HTF Order Block
        if htf_orderblock["valid"]:
            score += 10
            checks.append("✔ HTF Order Block")
        else:
            checks.append("✘ HTF Order Block")

        # Killzone
        if killzone:
            score += 3
            checks.append("✔ Kill Zone")
        else:
            checks.append("✘ Kill Zone")

        # Session
        if session:
            score += 2
            checks.append("✔ Session")
        else:
            checks.append("✘ Session")

        return {
            "score": score,
            "checks": checks
        }
