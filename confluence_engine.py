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
        smt=None,
        orderblocks=None,
        fvg=None,
        market_phase=None,
        unicorn=None,
        cisd=None,
        volume_profile=None,
        institutional=None,
    ):

        score = 0
        checks = []
        entry_direction = entry.get("direction", "WAIT")

        # Multi Timeframe
        if mtf["valid"]:
            score += 10
            checks.append("✔ Multi Timeframe")
        else:
            checks.append("✘ Multi Timeframe")

        # Trend
        trend_ok = (
            (trend["trend"] == "BULLISH" and entry_direction == "LONG") or
            (trend["trend"] == "BEARISH" and entry_direction == "SHORT")
        )

        if trend_ok:
            score += 10
            checks.append("✔ Trend")
        else:
            checks.append("✘ Trend")
            score -= 4

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
        if liquidity_sweep.get("is_sweep"):
            sweep_score = min(15, int(liquidity_sweep.get("strength_score", 0) / 8))
            score += sweep_score
            checks.append(f"✔ Liquidity Sweep ({liquidity_sweep.get('strength_score', 0)}%)")
        elif liquidity_sweep.get("is_breakout"):
            score += 2
            checks.append("◐ Liquidity Breakout")
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

        # SMT Divergence
        if smt and smt.get("active"):
            smt_direction = smt.get("direction")

            if (smt_direction == "BULLISH" and entry_direction == "LONG") or (
                smt_direction == "BEARISH" and entry_direction == "SHORT"
            ):
                score += 12
                checks.append(f"✔ SMT {smt_direction} ({smt.get('confidence', 0)}%)")
            else:
                score -= 4
                checks.append(f"◐ SMT {smt_direction} ({smt.get('confidence', 0)}%)")
        else:
            checks.append("✘ SMT")

        # Stack Confluence: Sweep + OB + FVG + SMT + Market Phase
        stack_ok = (
            liquidity_sweep.get("is_sweep")
            and bool(orderblocks)
            and bool(fvg)
            and bool(smt and smt.get("active"))
            and bool(market_phase and market_phase.get("phase") in ["Expansion", "Trending", "Reversal"])
        )

        if stack_ok:
            score += 18
            checks.append("✔ Stack Confluence (Sweep+OB+FVG+SMT+Phase)")
        else:
            checks.append("✘ Stack Confluence")

        # Unicorn Setup
        if unicorn and unicorn.get("active"):
            unicorn_confidence = unicorn.get("confidence", 0)
            score += min(20, int(unicorn_confidence / 5))
            checks.append(f"✔ Unicorn ({unicorn_confidence}%)")

            best = unicorn.get("best") or {}
            direction = best.get("direction")
            if (direction == "BULLISH" and entry_direction == "LONG") or (
                direction == "BEARISH" and entry_direction == "SHORT"
            ):
                score += 6
                checks.append("✔ Unicorn Direction Match")
            else:
                score -= 6
                checks.append("◐ Unicorn Direction Mismatch")
        else:
            checks.append("✘ Unicorn")

        # CISD
        if cisd and cisd.get("active"):
            cisd_direction = cisd.get("direction")
            cisd_confidence = cisd.get("confidence", 0)

            if (cisd_direction == "BULLISH" and entry_direction == "LONG") or (
                cisd_direction == "BEARISH" and entry_direction == "SHORT"
            ):
                score += min(16, int(cisd_confidence / 6))
                checks.append(f"✔ CISD {cisd_direction} ({cisd_confidence}%)")
            else:
                score -= 3
                checks.append(f"◐ CISD {cisd_direction} ({cisd_confidence}%)")
        else:
            checks.append("✘ CISD")

        # Volume Profile
        if volume_profile and volume_profile.get("active"):
            vp_direction = volume_profile.get("direction", "NONE")
            vp_confidence = volume_profile.get("confidence", 0)

            if (vp_direction == "BULLISH" and entry_direction == "LONG") or (
                vp_direction == "BEARISH" and entry_direction == "SHORT"
            ):
                score += min(14, int(vp_confidence / 7))
                checks.append(f"✔ Volume Profile {vp_direction} ({vp_confidence}%)")
            else:
                score -= 5
                checks.append(f"◐ Volume Profile {vp_direction} ({vp_confidence}%)")
        else:
            checks.append("✘ Volume Profile")

        # Institutional Flow
        if institutional and institutional.get("active"):
            institutional_direction = institutional.get("direction", "NONE")
            institutional_confidence = institutional.get("confidence", 0)

            if (institutional_direction == "LONG" and entry_direction == "LONG") or (
                institutional_direction == "SHORT" and entry_direction == "SHORT"
            ):
                score += min(18, int(institutional_confidence / 5))
                checks.append(f"✔ Institutional Flow {institutional_direction} ({institutional_confidence}%)")
            else:
                score -= 6
                checks.append(f"◐ Institutional Flow {institutional_direction} ({institutional_confidence}%)")
        else:
            checks.append("✘ Institutional Flow")

        return {
            "score": score,
            "checks": checks
        }
