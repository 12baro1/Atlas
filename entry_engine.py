"""
entry_engine.py
Atlas SMC Entry Engine
"""

class EntryEngine:

    def generate(self, mtf, structure, fvg, orderblocks):

        result = {
            "valid": False,
            "direction": "NONE",
            "reason": "",
            "entry": None,
            "stop_loss": None
        }

        if not mtf.get("valid", False):
            result["reason"] = "MTF not aligned"
            return result

        if not structure:
            result["reason"] = "No structure"
            return result

        last = structure[-1]
        label = last.get("label")

        if mtf["entry"] == "LONG":

            if label not in ["HH", "HL"]:
                result["reason"] = "No bullish structure"
                return result

            if not fvg:
                result["reason"] = "No bullish FVG"
                return result

            if not orderblocks:
                result["reason"] = "No bullish Order Block"
                return result

            last_fvg = fvg[-1]
            last_ob = orderblocks[-1]

            result["valid"] = True
            result["direction"] = "LONG"
            result["entry"] = last_fvg["to"]      # FVG'nin alt sınırı
            result["stop_loss"] = last_ob["low"]  # Order Block altı
            result["reason"] = "Bullish setup confirmed"
            return result

        if mtf["entry"] == "SHORT":

            if label not in ["LL", "LH"]:
                result["reason"] = "No bearish structure"
                return result

            if not fvg:
                result["reason"] = "No bearish FVG"
                return result

            if not orderblocks:
                result["reason"] = "No bearish Order Block"
                return result

            last_fvg = fvg[-1]
            last_ob = orderblocks[-1]

            result["valid"] = True
            result["direction"] = "SHORT"
            result["entry"] = last_fvg["from"]     # FVG'nin üst sınırı
            result["stop_loss"] = last_ob["high"]  # Order Block üstü
            result["reason"] = "Bearish setup confirmed"
            return result

        result["reason"] = "No entry"
        return result
