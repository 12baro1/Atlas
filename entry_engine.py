"""
entry_engine.py
Atlas Entry Engine v5
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
        # Best FVG
        # -------------------------

        selected_fvg = None

        for gap in reversed(fvg):

            if gap.get("filled", False):
                continue

            if direction == "LONG" and gap["type"] == "BULLISH":
                selected_fvg = gap
                break

            if direction == "SHORT" and gap["type"] == "BEARISH":
                selected_fvg = gap
                break

        if selected_fvg:
            result["score"] += 25
            result["checks"].append("✓ Fresh FVG")
        else:
            result["checks"].append("✗ FVG")

        # -------------------------
        # Best Order Block
        # -------------------------

        selected_ob = None

        for ob in reversed(orderblocks):

            if ob.get("mitigated", False):
                continue

            if direction == "LONG" and ob["type"] == "BULLISH":
                selected_ob = ob
                break

            if direction == "SHORT" and ob["type"] == "BEARISH":
                selected_ob = ob
                break

        if selected_ob:
            result["score"] += 25
            result["checks"].append("✓ Fresh Order Block")
        else:
            result["checks"].append("✗ Order Block")

        # -------------------------
        # Entry
        # -------------------------

        if direction == "LONG":

            if selected_fvg:
                result["entry"] = selected_fvg["to"]
            elif selected_ob:
                result["entry"] = selected_ob["high"]

            if selected_ob:
                result["stop_loss"] = selected_ob["low"]
            elif selected_fvg:
                result["stop_loss"] = selected_fvg["from"]

        else:

            if selected_fvg:
                result["entry"] = selected_fvg["from"]
            elif selected_ob:
                result["entry"] = selected_ob["low"]

            if selected_ob:
                result["stop_loss"] = selected_ob["high"]
            elif selected_fvg:
                result["stop_loss"] = selected_fvg["to"]

        # -------------------------
        # Risk Filter
        # -------------------------

        if (
            result["entry"] is not None
            and result["stop_loss"] is not None
        ):

            distance = abs(
                result["entry"] -
                result["stop_loss"]
            )

            if distance > 0:
                result["score"] += 30
            else:
                result["checks"].append("✗ Invalid SL")

        result["valid"] = (
            result["score"] >= 60
            and result["entry"] is not None
            and result["stop_loss"] is not None
        )

        if result["valid"]:
            result["reason"] = "High probability setup"
        else:
            result["reason"] = "Weak setup"

        return result
