"""Advisory 15m evidence for a structurally valid Atlas entry.

15m events refine execution; they do not veto a valid higher-timeframe POI.
"""
class EntryConfirmationEngine:
    def confirm(self, mtf, structure, fvg, entry, current_price=None):
        entry = entry if isinstance(entry, dict) else {}
        mtf = mtf if isinstance(mtf, dict) else {}
        structure = structure if isinstance(structure, list) else []
        fvg = fvg if isinstance(fvg, list) else []
        result = {
            "confirmed": False,
            "reason": "Entry/POI confirmation unavailable",
            "confirmation_profile": entry.get("confirmation_profile") or {"mode": "EVIDENCE_BALANCE"},
            "requirements": {},
            "advisory_only": True,
        }
        if not entry.get("valid"):
            result["reason"] = "Entry not valid"
            return result
        if not mtf.get("valid"):
            result["reason"] = "Primary MTF direction is not valid"
            return result

        direction = str(entry.get("direction", "")).upper()
        if direction not in {"LONG", "SHORT"}:
            result["reason"] = "No direction"
            return result

        expected_fvg = "BULLISH" if direction == "LONG" else "BEARISH"
        try:
            price = float(current_price) if current_price is not None else None
        except (TypeError, ValueError, OverflowError):
            price = None

        active_fvg = False
        for gap in fvg:
            if not isinstance(gap, dict) or str(gap.get("type", "")).upper() != expected_fvg or gap.get("filled"):
                continue
            try:
                lower, upper = sorted((float(gap.get("from")), float(gap.get("to"))))
            except (TypeError, ValueError, OverflowError):
                continue
            if lower <= 0 or lower >= upper:
                continue
            if price is not None and ((direction == "LONG" and lower > price) or (direction == "SHORT" and upper < price)):
                continue
            active_fvg = True
            break

        zone = entry.get("poi_zone") if isinstance(entry.get("poi_zone"), dict) else {}
        try:
            low, high = float(zone.get("low")), float(zone.get("high"))
            valid_zone = 0 < low < high
        except (TypeError, ValueError, OverflowError):
            valid_zone = False
        # EntryEngine has already selected and validated the structural POI.
        # Requiring a second fresh FVG or OB+OTE here duplicated the POI gate
        # and silently made OTE mandatory for order-block entries.
        if not valid_zone:
            result["reason"] = "Selected structural POI is unavailable"
            return result
        poi_source = str(entry.get("poi_source") or "STRUCTURAL_POI").upper()
        poi_confirmation = "FVG" if active_fvg else poi_source

        breaks = [x for x in structure if isinstance(x, dict) and (x.get("bos") or x.get("choch"))]
        latest = breaks[-1] if breaks else None
        expected = "BULLISH" if direction == "LONG" else "BEARISH"
        event_direction = str((latest or {}).get("direction", "")).upper()
        conflict = bool(latest and event_direction in {"BULLISH", "BEARISH"} and event_direction != expected)
        mode = "NO_15M_BREAK" if latest is None else ("COUNTER_DIRECTIONAL_EVIDENCE" if conflict else "DIRECTIONAL_EVIDENCE")
        result.update({
            "confirmed": True,
            "confirmation_mode": mode,
            "poi_confirmation": poi_confirmation,
            "reentry_triggered": False,
            "15m_conflict": conflict,
            "15m_latest_event": str((latest or {}).get("label", "NONE")),
            "reason": (
                "Valid MTF + POI; opposing 15m evidence retained as execution input"
                if conflict else
                "Valid MTF + selected structural POI; 15m evidence used as entry refinement"
            ),
        })
        return result
