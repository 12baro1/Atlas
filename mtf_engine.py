"""
mtf_engine.py
Atlas SMC Engine
"""

class MTFEngine:

    def detect(self, weekly, daily, h4, m15):

        result = {
            "weekly": "NEUTRAL",
            "daily": "NEUTRAL",
            "h4": "NEUTRAL",
            "entry": "NONE",
            "valid": False
        }

        # Weekly
        if weekly:
            last = weekly[-1]["label"]

            if last in ["HH", "HL"]:
                result["weekly"] = "BULLISH"
            elif last in ["LL", "LH"]:
                result["weekly"] = "BEARISH"

        # Daily
        if daily:
            last = daily[-1]["label"]

            if last in ["HH", "HL"]:
                result["daily"] = "BULLISH"
            elif last in ["LL", "LH"]:
                result["daily"] = "BEARISH"

        # H4
        if h4:
            last = h4[-1]["label"]

            if last in ["HH", "HL"]:
                result["h4"] = "BULLISH"
            elif last in ["LL", "LH"]:
                result["h4"] = "BEARISH"

        # Entry
        if (
            result["weekly"] == "BULLISH"
            and result["daily"] == "BULLISH"
            and result["h4"] == "BULLISH"
        ):
            result["entry"] = "LONG"
            result["valid"] = True

        elif (
            result["weekly"] == "BEARISH"
            and result["daily"] == "BEARISH"
            and result["h4"] == "BEARISH"
        ):
            result["entry"] = "SHORT"
            result["valid"] = True

        return result
