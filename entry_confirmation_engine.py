"""Final 15m structure confirmation for an executable SMC entry."""


class EntryConfirmationEngine:

    def confirm(self, mtf, structure, fvg, entry, current_price=None):
        entry = entry if isinstance(entry, dict) else {}
        result = {
            "confirmed": False,
            "reason": "Weak confirmation",
            "confirmation_profile": entry.get("confirmation_profile") or {"mode": "UNAVAILABLE"},
            "requirements": entry.get("confirmation_requirements") or {},
        }

        mtf = mtf if isinstance(mtf, dict) else {}
        structure = structure if isinstance(structure, list) else []
        fvg = fvg if isinstance(fvg, list) else []

        if not entry.get("valid"):
            result["reason"] = "Entry not valid"
            return result
        if not mtf.get("valid"):
            result["reason"] = "MTF not aligned"
            return result
        if not structure:
            result["reason"] = "No structure"
            return result

        direction = str(entry.get("direction", "")).upper()
        expected = "BULLISH" if direction == "LONG" else "BEARISH" if direction == "SHORT" else None
        if expected is None:
            result["reason"] = "No direction"
            return result

        break_positions = [
            i for i, item in enumerate(structure)
            if isinstance(item, dict) and (item.get("bos") or item.get("choch"))
        ]
        if not break_positions:
            result["reason"] = "15m directional BOS/CHoCH missing"
            return result

        last_break_position = break_positions[-1]
        last_break = structure[last_break_position]
        label = str(last_break.get("label", "")).upper()
        event_direction = str(last_break.get("direction", "")).upper()
        confirmation_mode = "directional_break"

        if event_direction != expected:
            # A counter-directional CHoCH is a confirmed structural reversal,
            # not a pullback; it remains an unconditional rejection.
            if last_break.get("choch"):
                result["reason"] = "Latest 15m CHoCH reverses entry direction"
                return result

            prior_aligned_break = any(
                str(structure[i].get("direction", "")).upper() == expected
                and bool(structure[i].get("bos"))
                for i in break_positions[:-1]
            )
            if not prior_aligned_break:
                result["reason"] = "Latest 15m break opposes entry direction without a prior aligned BOS"
                return result

            recovery_label = "HL" if direction == "LONG" else "LH"
            recovery_kind = "LOW" if direction == "LONG" else "HIGH"
            reclaim_kind = "HIGH" if direction == "LONG" else "LOW"
            post_break_swings = [
                item for item in structure[last_break_position + 1:]
                if isinstance(item, dict)
            ]

            reclaimed_swing = any(
                str(item.get("label", "")).upper() == recovery_label
                and str(item.get("kind", item.get("type", ""))).upper() == recovery_kind
                for item in post_break_swings
            )

            try:
                price = float(current_price) if current_price is not None else None
            except (TypeError, ValueError, OverflowError):
                price = None

            reclaim_pivots = []
            for item in post_break_swings:
                kind = str(item.get("kind", item.get("type", ""))).upper()
                if kind != reclaim_kind:
                    continue
                try:
                    pivot_price = float(item.get("price", item.get("high" if direction == "LONG" else "low")))
                except (TypeError, ValueError, OverflowError):
                    continue
                if pivot_price > 0:
                    reclaim_pivots.append(pivot_price)

            reclaim_source = "post_break_pullback"
            # A confirmed counter-BOS can occur before the next pullback pivot
            # is confirmed. In that case, use the last pre-break structure level
            # as a stricter reclaim threshold. This requires price to recover
            # the prior range boundary, not merely bounce from the counter-BOS.
            if not reclaim_pivots:
                reclaim_source = "prior_structure_boundary"
                for item in reversed(structure[:last_break_position]):
                    kind = str(item.get("kind", item.get("type", ""))).upper()
                    if kind != reclaim_kind:
                        continue
                    try:
                        pivot_price = float(item.get("price", item.get("high" if direction == "LONG" else "low")))
                    except (TypeError, ValueError, OverflowError):
                        continue
                    if pivot_price > 0:
                        reclaim_pivots.append(pivot_price)
                        break

            reclaimed_price = False
            if price is not None and reclaim_pivots:
                reclaim_level = reclaim_pivots[-1]
                reclaimed_price = price > reclaim_level if direction == "LONG" else price < reclaim_level

            reclaimed = reclaimed_swing or reclaimed_price
            if not reclaimed:
                result["reason"] = "Latest 15m break opposes entry direction without a reclaimed pullback swing"
                return result
            confirmation_mode = (
                "reclaimed_pullback" if reclaimed_swing else
                "reclaimed_pullback_price" if reclaim_source == "post_break_pullback" else
                "reclaimed_prior_structure_boundary"
            )

        elif direction == "LONG" and label != "HH":
            result["reason"] = "Bullish structural break missing"
            return result
        elif direction == "SHORT" and label != "LL":
            result["reason"] = "Bearish structural break missing"
            return result

        requirements = entry.get("confirmation_requirements") if isinstance(entry.get("confirmation_requirements"), dict) else {}
        if requirements.get("require_choch_or_reclaim") and confirmation_mode == "directional_break" and not last_break.get("choch"):
            reasons = ", ".join(requirements.get("reasons") or [])
            result["reason"] = (
                "Secondary-engine conflict requires 15m CHoCH or reclaimed pullback structure"
                + (f" ({reasons})" if reasons else "")
            )
            return result

        expected_fvg = "BULLISH" if direction == "LONG" else "BEARISH"
        try:
            price = float(current_price) if current_price is not None else None
        except (TypeError, ValueError):
            price = None

        active_fvg = False
        for gap in fvg:
            if not isinstance(gap, dict):
                continue
            if str(gap.get("type", "")).upper() != expected_fvg or bool(gap.get("filled", False)):
                continue
            try:
                lower = min(float(gap.get("from")), float(gap.get("to")))
                upper = max(float(gap.get("from")), float(gap.get("to")))
            except (TypeError, ValueError):
                continue
            if lower <= 0 or lower >= upper:
                continue
            if price is not None:
                if direction == "LONG" and lower > price:
                    continue
                if direction == "SHORT" and upper < price:
                    continue
            active_fvg = True
            break
        # A fresh directional FVG is the preferred confirmation context.
        # In its absence, an unmitigated directional OB already selected by
        # EntryEngine is acceptable only when it overlaps the 4H OTE.
        poi_zone = entry.get("poi_zone") if isinstance(entry.get("poi_zone"), dict) else {}
        try:
            poi_low = float(poi_zone.get("low"))
            poi_high = float(poi_zone.get("high"))
            valid_poi_zone = 0 < poi_low < poi_high
        except (TypeError, ValueError, OverflowError):
            valid_poi_zone = False
        ob_ote_confluence = bool(
            entry.get("poi_source") == "ORDER_BLOCK"
            and entry.get("ote_confluence")
            and valid_poi_zone
        )
        if not active_fvg and not ob_ote_confluence:
            result["reason"] = "No unfilled directional FVG or valid OB+OTE confluence"
            return result

        result["confirmed"] = True
        result["confirmation_mode"] = confirmation_mode
        result["poi_confirmation"] = "FVG" if active_fvg else "ORDER_BLOCK_OTE"
        result["reason"] = (
            "15m reclaimed pullback structure confirmed with "
            + ("directional FVG" if active_fvg else "directional OB + 4H OTE")
            if confirmation_mode.startswith("reclaimed_pullback")
            else "15m structure break confirmed with "
            + ("directional FVG" if active_fvg else "directional OB + 4H OTE")
        )
        return result
