"""
confluence_engine.py
Atlas Confluence Engine v2
"""


class ConfluenceEngine:

    @staticmethod
    def _claim_event_id(module, seen_event_ids):
        if not isinstance(module, dict):
            return True
        event_id = module.get("event_id")
        if not event_id and isinstance(module.get("best"), dict):
            event_id = module["best"].get("event_id")
        if not event_id:
            for nested_key in ("cvd", "volume_delta", "snapshot"):
                nested = module.get(nested_key)
                if isinstance(nested, dict) and nested.get("event_id"):
                    event_id = nested["event_id"]
                    break
        if not event_id:
            return True
        identity = str(event_id).strip()
        if not identity:
            return True
        if identity in seen_event_ids:
            return False
        seen_event_ids.add(identity)
        return True

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
        trendline_sweep=None,
        ifvg=None,
        eqh_eql=None,
        internal_structure=None,
        current_index=None,
    ):

        score = 0
        checks = []
        entry_direction = entry.get("direction", "WAIT")
        seen_event_ids = set()

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

        # EntryConfirmation currently confirms MTF + POI availability; it is
        # not an independent 15m market event and must not add another full vote.
        if confirmation["confirmed"]:
            checks.append("◐ Confirmation (MTF/POI context; no additive score)")
        else:
            checks.append("✘ Confirmation")

        # Premium / Discount
        if premium_discount["valid"]:
            score += 8
            checks.append("✔ Premium Zone")
        else:
            checks.append("✘ Premium Zone")

        # Liquidity sweep must be on the correct side for the proposed reversal.
        self._claim_event_id(liquidity_sweep, seen_event_ids)
        expected_sweep = bool(liquidity_sweep.get("sell_side")) if entry_direction == "LONG" else bool(liquidity_sweep.get("buy_side"))
        opposing_sweep = bool(liquidity_sweep.get("buy_side")) if entry_direction == "LONG" else bool(liquidity_sweep.get("sell_side"))
        if liquidity_sweep.get("is_sweep") and expected_sweep and not opposing_sweep and not liquidity_sweep.get("ambiguous_sweep"):
            post = liquidity_sweep.get("post_structure") or {}
            if post.get("confirmed") and post.get("direction") != ("BULLISH" if entry_direction == "LONG" else "BEARISH"):
                score -= 8
                checks.append("✘ Liquidity Sweep Structure Direction")
            else:
                sweep_score = min(15, int(liquidity_sweep.get("strength_score", 0) / 8))
                score += sweep_score
                checks.append(f"✔ Directional Liquidity Sweep ({liquidity_sweep.get('strength_score', 0)}%)")
        elif liquidity_sweep.get("is_breakout"):
            score += 2
            checks.append("◐ Liquidity Breakout")
        elif liquidity_sweep.get("is_sweep"):
            score -= 10
            checks.append("✘ Liquidity Sweep Direction Mismatch")
        else:
            checks.append("✘ Liquidity Sweep")

        # OTE can qualify through the actual executable POI overlap, even when
        # current market price has not yet retraced into the pending LIMIT zone.
        if ote.get("valid") or entry.get("ote_confluence"):
            score += 8
            checks.append("✔ OTE + POI")
        else:
            checks.append("✘ OTE + POI")

        # A breaker is the inverse of the failed OB; only its new direction
        # should support confluence.
        expected_poi = "BULLISH" if entry_direction == "LONG" else "BEARISH"
        breaker_items = [
            item for item in (breaker or [])
            if isinstance(item, dict) and item.get("breaker")
            and self._claim_event_id(item, seen_event_ids)
        ]
        matching_breaker = any(str(item.get("type", "")).upper() == expected_poi for item in breaker_items)
        opposing_breaker = any(str(item.get("type", "")).upper() != expected_poi for item in breaker_items)
        if matching_breaker:
            score += 5
            checks.append("✔ Directional Breaker Block")
        elif opposing_breaker:
            score -= 2
            checks.append("◐ Breaker Block (opposing direction)")
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

        # Killzone and session describe the same clock context; award once.
        if killzone or session:
            score += 2
        checks.append("✔ Kill Zone" if killzone else "✘ Kill Zone")
        checks.append("✔ Session" if session else "✘ Session")

        # SMT Divergence
        if smt and smt.get("active") and self._claim_event_id(smt, seen_event_ids):
            smt_direction = smt.get("direction")

            if (smt_direction == "BULLISH" and entry_direction == "LONG") or (
                smt_direction == "BEARISH" and entry_direction == "SHORT"
            ):
                score += 12
                checks.append(f"✔ SMT {smt_direction} ({smt.get('confidence', 0)}%)")
            else:
                score -= 4
                checks.append(f"◐ SMT {smt_direction} ({smt.get('confidence', 0)}%)")
        elif smt and smt.get("active"):
            checks.append("◐ SMT duplicate event suppressed")
        else:
            checks.append("✘ SMT")

        # Stack Confluence uses only fresh POIs matching the intended direction.
        expected_poi = "BULLISH" if entry_direction == "LONG" else "BEARISH"
        directional_ob = any(
            isinstance(item, dict) and item.get("type") == expected_poi and not item.get("mitigated")
            for item in (orderblocks or [])
        )
        directional_fvg = any(
            isinstance(item, dict) and item.get("type") == expected_poi and not item.get("filled")
            for item in (fvg or [])
        )
        directional_sweep = (
            liquidity_sweep.get("is_sweep")
            and expected_sweep
            and not opposing_sweep
            and not liquidity_sweep.get("ambiguous_sweep")
        )
        stack_ok = (
            directional_sweep
            and directional_ob
            and directional_fvg
            and bool(smt and smt.get("active") and smt.get("direction") == ("BULLISH" if entry_direction == "LONG" else "BEARISH"))
            and bool(market_phase and market_phase.get("phase") in ["Expansion", "Trending", "Reversal"])
        )

        if stack_ok:
            # Synergy bonus only: the underlying sweep/POI/SMT/phase evidence
            # already received its own component score above.
            score += 6
            checks.append("✔ Stack Confluence synergy (+6)")
        else:
            checks.append("✘ Stack Confluence")

        # Unicorn Setup
        if unicorn and unicorn.get("active") and self._claim_event_id(unicorn, seen_event_ids):
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
        elif unicorn and unicorn.get("active"):
            checks.append("◐ Unicorn duplicate event suppressed")
        else:
            checks.append("✘ Unicorn")

        # CISD
        if cisd and cisd.get("active") and self._claim_event_id(cisd, seen_event_ids):
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
        elif cisd and cisd.get("active"):
            checks.append("◐ CISD duplicate event suppressed")
        else:
            checks.append("✘ CISD")

        # Volume Profile
        if volume_profile and volume_profile.get("active") and self._claim_event_id(volume_profile, seen_event_ids):
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
        elif volume_profile and volume_profile.get("active"):
            checks.append("◐ Volume Profile duplicate event suppressed")
        else:
            checks.append("✘ Volume Profile")

        # Institutional Flow
        if institutional and institutional.get("active") and self._claim_event_id(institutional, seen_event_ids):
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
        elif institutional and institutional.get("active"):
            checks.append("◐ Institutional Flow duplicate event suppressed")
        else:
            checks.append("✘ Institutional Flow")

        # Trendline Sweep
        if trendline_sweep and trendline_sweep.get("active") and self._claim_event_id(trendline_sweep, seen_event_ids):
            sweep_dir = trendline_sweep.get("direction")
            if (sweep_dir == "SELL_SIDE" and entry_direction == "LONG") or (
                sweep_dir == "BUY_SIDE" and entry_direction == "SHORT"
            ):
                score += 8
                checks.append("✔ Trendline Sweep")
            else:
                score -= 2
                checks.append("◐ Trendline Sweep (yön uyuşmaz)")
        elif trendline_sweep and trendline_sweep.get("active"):
            checks.append("◐ Trendline Sweep duplicate event suppressed")
        else:
            checks.append("✘ Trendline Sweep")

        # Equal High / Equal Low
        eqh_eql_event_ids = [
            item.get("event_id") for key in ("eqh", "eql")
            for item in ((eqh_eql or {}).get(key) or [])
            if isinstance(item, dict) and item.get("event_id")
        ]
        eqh_eql_unique = True
        for event_id in eqh_eql_event_ids:
            if event_id in seen_event_ids:
                eqh_eql_unique = False
            else:
                seen_event_ids.add(event_id)
        if eqh_eql and eqh_eql.get("active") and eqh_eql_unique:
            if eqh_eql.get("eql") and entry_direction == "LONG":
                score += 6
                checks.append("✔ Equal Low (Sweep hedefi)")
            elif eqh_eql.get("eqh") and entry_direction == "SHORT":
                score += 6
                checks.append("✔ Equal High (Sweep hedefi)")
        else:
            checks.append("✘ Equal HL")

        # Inverse FVG: the original gap direction flips after inversion.
        recent_ifvg = []
        for zone in (ifvg or []):
            if not self._claim_event_id(zone, seen_event_ids):
                continue
            if not isinstance(zone, dict) or not zone.get("inverted"):
                continue
            try:
                index = int(zone.get("index", current_index if current_index is not None else 0))
            except (TypeError, ValueError, OverflowError):
                continue
            if current_index is not None and index < int(current_index) - 48:
                continue
            recent_ifvg.append(zone)
        aligned_ifvg = any(
            ("SHORT" if str(zone.get("type", "")).upper() == "BULLISH" else "LONG")
            == entry_direction
            for zone in recent_ifvg
            if str(zone.get("type", "")).upper() in {"BULLISH", "BEARISH"}
        )
        opposing_ifvg = any(
            ("SHORT" if str(zone.get("type", "")).upper() == "BULLISH" else "LONG")
            != entry_direction
            for zone in recent_ifvg
            if str(zone.get("type", "")).upper() in {"BULLISH", "BEARISH"}
        )
        if aligned_ifvg:
            score += 6
            checks.append("✔ Directional Inverse FVG")
        elif opposing_ifvg:
            score -= 2
            checks.append("◐ Inverse FVG (opposing direction)")
        else:
            checks.append("✘ Inverse FVG")

        # Internal Structure is directional evidence, not a presence-only bonus.
        recent_internal = []
        for item in (internal_structure or []):
            if not isinstance(item, dict) or not self._claim_event_id(item, seen_event_ids):
                continue
            try:
                index = int(item.get("index", current_index if current_index is not None else 0))
            except (TypeError, ValueError, OverflowError):
                continue
            if current_index is None or index >= int(current_index) - 48:
                recent_internal.append(item)
        labels = [str(item.get("label", "")).upper() for item in recent_internal[-8:]]
        internal_bull = sum(label in {"HH", "HL"} for label in labels)
        internal_bear = sum(label in {"LH", "LL"} for label in labels)
        if entry_direction == "LONG" and internal_bull > internal_bear:
            score += 2
            checks.append(f"✔ Internal Structure bullish ({len(labels)} swing)")
        elif entry_direction == "SHORT" and internal_bear > internal_bull:
            score += 2
            checks.append(f"✔ Internal Structure bearish ({len(labels)} swing)")
        elif internal_bull or internal_bear:
            score -= 1
            checks.append("◐ Internal Structure opposing")

        return {
            "score": score,
            "checks": checks
        }
