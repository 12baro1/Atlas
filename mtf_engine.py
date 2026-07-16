"""
mtf_engine.py
Atlas SMC Engine
"""

class MTFEngine:

    def detect(self, weekly, daily, h4, entry):

        w = weekly[-1]["label"] if weekly else None
        d = daily[-1]["label"] if daily else None
        h = h4[-1]["label"] if h4 else None

        weekly_trend = "BULLISH" if w in ["HH", "HL"] else "BEARISH"
        daily_trend = "BULLISH" if d in ["HH", "HL"] else "BEARISH"
        h4_trend = "BULLISH" if h in ["HH", "HL"] else "BEARISH"

        entry_signal = "NONE"

        if weekly_trend == daily_trend == h4_trend == "BULLISH":
            entry_signal = "LONG"

        elif weekly_trend == daily_trend == h4_trend == "BEARISH":
            entry_signal = "SHORT"

        return {
            "weekly": weekly_trend,
            "daily": daily_trend,
            "h4": h4_trend,
            "entry": entry_signal,
            "valid": entry_signal != "NONE"
        }
