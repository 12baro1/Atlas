"""
entry_engine.py
Atlas SMC Entry Engine v2
"""

class EntryEngine:

    def generate(self, mtf, structure, fvg, orderblocks):

        result = {
            "valid": False,
            "direction": "NONE",
            "entry": None,
            "stop_loss": None,
            "score": 0,
            "reason": "",
            "checks": []
        }

        direction = mtf.get("entry")

        if direction not in ["LONG", "SHORT"]:
            result["reason"] = "No MTF direction"
            return result

        result["direction"] = direction

        # -------------------------
        # Structure
        # -------------------------

        if structure:

            last = structure[-1]["label"]

            if direction == "LONG":

                if last in ["HH", "HL"]:
                    result["score"] += 20
                    result["checks"].append("✓ Bullish Structure")
                else:
                    result["checks"].append("✗ Bullish Structure")

            else:

                if last in ["LL", "LH"]:
                    result["score"] += 20
                    result["checks"].append("✓ Bearish Structure")
                else:
                    result["checks"].append("✗ Bearish Structure")

        # -------------------------
        # FVG
        # -------------------------

        selected_fvg = None

        for gap in reversed(fvg):

            if gap["filled"]:
                continue

            if gap["type"] == "BULLISH" and direction == "LONG":
                selected_fvg = gap
                break

            if gap["type"] == "BEARISH" and direction == "SHORT":
                selected_fvg = gap
                break

        if selected_fvg:

            result["score"] += 25
            result["checks"].append("✓ FVG")

        else:

            result["checks"].append("✗ FVG")

        # -------------------------
        # Order Block
        # -------------------------

        selected_ob = None

        for ob in reversed(orderblocks):

            if ob["mitigated"]:
                continue

            if ob["type"] == "BULLISH" and direction == "LONG":
                selected_ob = ob
                break

            if ob["type"] == "BEARISH" and direction == "SHORT":
                selected_ob = ob
                break

        if selected_ob:

            result["score"] += 25
            result["checks"].append("✓ Order Block")

        else:

            result["checks"].append("✗ Order Block")

        # -------------------------
        # Entry
        # -------------------------

        if selected_fvg and selected_ob:

            if direction == "LONG":

                result["entry"] = selected_fvg["to"]
                result["stop_loss"] = selected_ob["low"]

            else:

                result["entry"] = selected_fvg["from"]
                result["stop_loss"] = selected_ob["high"]

            result["score"] += 30

        result["valid"] = result["score"] >= 60

        if result["valid"]:
            result["reason"] = "High probability setup"
        else:
            result["reason"] = "Weak setup"

        return result
