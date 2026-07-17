"""
entry_confirmation_engine.py
Atlas SMC Entry Confirmation v2
"""

class EntryConfirmationEngine:

    def confirm(self, mtf, structure, fvg, entry):

        result = {
            "confirmed": False,
            "reason": "Weak confirmation"
        }

        if not entry["valid"]:
            result["reason"] = "Entry not valid"
            return result

        if not mtf["valid"]:
            result["reason"] = "MTF not aligned"
            return result

        if len(structure) == 0:
            result["reason"] = "No structure"
            return result

        last = structure[-1]["label"]

        if entry["direction"] == "LONG":

            if last not in ["HH", "HL"]:
                result["reason"] = "Bullish CHOCH missing"
                return result

        elif entry["direction"] == "SHORT":

            if last not in ["LL", "LH"]:
                result["reason"] = "Bearish CHOCH missing"
                return result

        else:
            result["reason"] = "No direction"
            return result

        if len(fvg) == 0:
            result["reason"] = "No active FVG"
            return result

        result["confirmed"] = True
        result["reason"] = "Entry confirmed"

        return result
