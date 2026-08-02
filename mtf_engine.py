"""
mtf_engine.py
Atlas SMC Engine
"""

class MTFEngine:

    def _trend_from_structure(self, structure):
        if not structure:
            return "NEUTRAL"

        label = structure[-1].get("label")
        if label in ["HH", "HL"]:
            return "BULLISH"
        if label in ["LL", "LH"]:
            return "BEARISH"
        return "NEUTRAL"

    def detect(self, weekly, daily, h4, entry):

        weekly_trend = self._trend_from_structure(weekly)
        daily_trend = self._trend_from_structure(daily)
        h4_trend = self._trend_from_structure(h4)

        bulls = [weekly_trend, daily_trend, h4_trend].count("BULLISH")
        bears = [weekly_trend, daily_trend, h4_trend].count("BEARISH")

        entry_signal = "NONE"

        if bulls >= 2:
            entry_signal = "LONG"

        elif bears >= 2:
            entry_signal = "SHORT"

        return {
            "trend": weekly_trend,
            "weekly": weekly_trend,
            "daily": daily_trend,
            "h4": h4_trend,
            "entry": entry_signal,
            "valid": entry_signal != "NONE"
        }
