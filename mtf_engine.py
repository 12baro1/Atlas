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
