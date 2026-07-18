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
        htf_fvg,
        killzone,
        session,
        breaker=None,
        eqh_eql=None,
        inducement=None
    ):

        score = 0
        checks = []

        # Multi Timeframe
        if mtf["valid"]:
            score += 10
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
            score += 15
            checks.append("✔ Entry")
        else:
            checks.append("✘ Entry")

        # Confirmation
        if confirmation["confirmed"]:
            score += 10
            checks.append("✔ Confirmation")
        else:
            checks.append("✘ Confirmation")

        # Premium / Discount
        if premium_discount["valid"]:
            score += 8
            checks.append("✔ Premium Zone")
        else:
            checks.append("✘ Premium Zone")

        # Liquidity Sweep
        liquidity_sweep_valid = False

        if isinstance(liquidity_sweep, dict):
            liquidity_sweep_valid = (
                liquidity_sweep.get("buy_side")
                or liquidity_sweep.get("sell_side")
            )
        else:
            liquidity_sweep_valid = bool(liquidity_sweep)

        if liquidity_sweep_valid:
            score += 10
            checks.append("✔ Liquidity Sweep")
        else:
            checks.append("✘ Liquidity Sweep")

        # OTE
        if ote["valid"]:
            score += 8
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

        # HTF FVG
        if htf_fvg["valid"]:
            score += 8
            checks.append("✔ HTF FVG")
        else:
            checks.append("✘ HTF FVG")

        # Equal High / Equal Low
        if eqh_eql and eqh_eql.get("valid"):
            score += 6
            checks.append("✔ EQH/EQL Liquidity")
        else:
            checks.append("✘ EQH/EQL Liquidity")

        # Inducement
        if inducement and inducement.get("valid"):
            score += 7
            checks.append("✔ Inducement")
        else:
            checks.append("✘ Inducement")

        # Killzone
        if killzone:
            score += 2
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
