"""Final 15m structure confirmation for an executable SMC entry."""


class EntryConfirmationEngine:

    def confirm(self, mtf, structure, fvg, entry):
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

        # A swing label alone (e.g. HL) is a location, not an entry trigger.
        # The latest confirmed 15m swing must have actually broken structure.
        last = structure[-1]
        label = str(last.get("label", "")).upper()
        event_direction = str(last.get("direction", "")).upper()
        if not (last.get("bos") or last.get("choch")) or event_direction != expected:
            result["reason"] = "15m directional BOS/CHoCH missing"
            return result

        if direction == "LONG" and label not in {"HH"}:
            result["reason"] = "Bullish structural break missing"
            return result
        if direction == "SHORT" and label not in {"LL"}:
            result["reason"] = "Bearish structural break missing"
            return result

        expected_fvg = "BULLISH" if direction == "LONG" else "BEARISH"
        active_fvg = any(
            isinstance(gap, dict)
            and str(gap.get("type", "")).upper() == expected_fvg
            and not bool(gap.get("filled", False))
            for gap in fvg
        )
        if not active_fvg:
            result["reason"] = "No unfilled directional FVG"
            return result

        result["confirmed"] = True
        result["reason"] = "15m structure break and directional FVG confirmed"
        return result
