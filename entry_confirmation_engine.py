"""
entry_confirmation_engine.py
Atlas SMC Entry Confirmation v2
"""

class EntryConfirmationEngine:

    def confirm(self, mtf, structure, fvg):

        result = {
            "confirmed": False,
            "score": 0,
            "reason": "",
            "checks": []
        }

        # MTF
        if mtf.get("valid", False):
            result["score"] += 30
            result["checks"].append("✓ MTF aligned")
        else:
            result["checks"].append("✗ MTF not aligned")

        # Structure
        if structure:

            last = structure[-1]["label"]

            if mtf.get("entry") == "LONG":

                if last in ["HH", "HL"]:
                    result["score"] += 30
                    result["checks"].append("✓ Bullish Structure")
                else:
                    result["checks"].append("✗ Bullish Structure")

            elif mtf.get("entry") == "SHORT":

                if last in ["LL", "LH"]:
                    result["score"] += 30
                    result["checks"].append("✓ Bearish Structure")
                else:
                    result["checks"].append("✗ Bearish Structure")

        else:
            result["checks"].append("✗ No Structure")

        # FVG
        if len(fvg) > 0:
            result["score"] += 40
            result["checks"].append("✓ FVG")
        else:
            result["checks"].append("✗ No FVG")

        # Final
        result["confirmed"] = result["score"] >= 60

        if result["confirmed"]:
            result["reason"] = "Entry confirmed"
        else:
            result["reason"] = "Weak confirmation"

        return result
