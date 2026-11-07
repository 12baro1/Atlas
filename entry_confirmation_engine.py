"""Final 15m structure confirmation for an executable SMC entry."""


class EntryConfirmationEngine:

    def confirm(self, mtf, structure, fvg, entry, current_price=None):
        result = {"confirmed": False, "reason": "Weak confirmation"}

        mtf = mtf if isinstance(mtf, dict) else {}
        entry = entry if isinstance(entry, dict) else {}
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

        # Keep the latest confirmed directional break active through ordinary
        # pullback pivots (HL/LH). It expires only when a newer opposing BOS/CHoCH
        # appears; a swing label by itself is not a new break.
        break_events = [
            item for item in structure
            if isinstance(item, dict) and (item.get("bos") or item.get("choch"))
        ]
        if not break_events:
            result["reason"] = "15m directional BOS/CHoCH missing"
            return result

        last_break = break_events[-1]
        label = str(last_break.get("label", "")).upper()
        event_direction = str(last_break.get("direction", "")).upper()
        confirmation_mode = "directional_break"

        if event_direction != expected:
            # An opposing CHoCH is a genuine structural reversal and always
            # invalidates the prior directional confirmation.
            if last_break.get("choch"):
                result["reason"] = "Latest 15m CHoCH reverses entry direction"
                return result

            # A counter-directional BOS can be a failed liquidity probe during
            # a pullback. Preserve continuation only when a prior BOS in the
            # intended direction exists and price structure subsequently prints
            # a reclaimed HL (LONG) / LH (SHORT). This is not a generic bypass.
            prior_aligned_break = any(
                str(item.get("direction", "")).upper() == expected
                and bool(item.get("bos"))
                for item in break_events[:-1]
            )
            recovery_label = "HL" if direction == "LONG" else "LH"
            recovery_kind = "LOW" if direction == "LONG" else "HIGH"
            reclaim_kind = "HIGH" if direction == "LONG" else "LOW"
            last_break_position = structure.index(last_break)
            post_break_swings = [
                item for item in structure[last_break_position + 1:]
                if isinstance(item, dict)
            ]

            # Preferred confirmation: the structure engine has explicitly
            # labelled a higher low / lower high after the counter BOS.
            reclaimed_swing = any(
                str(item.get("label", "")).upper() == recovery_label
                and str(item.get("kind", item.get("type", ""))).upper() == recovery_kind
                for item in post_break_swings
            )

            # Some 15m feeds have not yet relabelled the recovery pivot as
            # HL/LH, even though the pullback's opposing swing is confirmed.
            # In that case require the latest close to reclaim that pivot:
            # LONG must close above the post-break HIGH; SHORT below the LOW.
            # A counter-directional CHoCH is still an unconditional rejection.
            reclaimed_price = False
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
            if price is not None and reclaim_pivots:
                reclaim_level = reclaim_pivots[-1]
                reclaimed_price = price > reclaim_level if direction == "LONG" else price < reclaim_level

            reclaimed = reclaimed_swing or reclaimed_price
            if not (prior_aligned_break and reclaimed):
                result["reason"] = "Latest 15m break opposes entry direction without a reclaimed pullback swing"
                return result
            confirmation_mode = "reclaimed_pullback" if reclaimed_swing else "reclaimed_pullback_price"

        elif direction == "LONG" and label != "HH":
            result["reason"] = "Bullish structural break missing"
            return result
        elif direction == "SHORT" and label != "LL":
            result["reason"] = "Bearish structural break missing"
            return result

        expected_fvg = "BULLISH" if direction == "LONG" else "BEARISH"
        # Confirmation must use an FVG that is actually reachable as a
        # pullback zone, matching EntryEngine's price-side selection rule.
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
        if not active_fvg:
            result["reason"] = "No unfilled directional FVG"
            return result

        result["confirmed"] = True
        result["confirmation_mode"] = confirmation_mode
        result["reason"] = (
            "15m reclaimed pullback structure and directional FVG confirmed"
            if confirmation_mode.startswith("reclaimed_pullback")
            else "15m structure break and directional FVG confirmed"
        )
        return result
