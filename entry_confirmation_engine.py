"""
entry_confirmation_engine.py
Atlas 15M Entry Confirmation
"""

class EntryConfirmationEngine:

    def confirm(self, mtf, structure, fvg):

        result = {
            "confirmed": False,
            "reason": ""
        }

        if not mtf.get("valid", False):
            result["reason"] = "MTF not aligned"
            return result

        if not structure:
            result["reason"] = "No market structure"
            return result

        last = structure[-1]["label"]

        if mtf["entry"] == "LONG":
            if last not in ["HH", "HL"]:
                result["reason"] = "15M bullish CHOCH missing"
                return result

            if len(fvg) == 0:
                result["reason"] = "No FVG"
                return result

            result["confirmed"] = True
            result["reason"] = "15M LONG confirmed"
            return result

        if mtf["entry"] == "SHORT":
            if last not in ["LL", "LH"]:
                result["reason"] = "15M bearish CHOCH missing"
                return result

            if len(fvg) == 0:
                result["reason"] = "No FVG"
                return result

            result["confirmed"] = True
            result["reason"] = "15M SHORT confirmed"
            return result

        result["reason"] = "No entry"
        return result
