"""
trend_engine.py
Atlas Trend Engine v4
"""


class TrendEngine:

    def calculate(self, mtf):

        weekly = mtf.get("weekly")
        daily = mtf.get("daily")
        h4 = mtf.get("h4")

        bullish = 0
        bearish = 0

        for tf in [weekly, daily, h4]:

            if tf == "BULLISH":
                bullish += 1

            elif tf == "BEARISH":
                bearish += 1

        if bullish >= 2:
            return {
                "trend": "BULLISH",
                "strength": bullish,
                "score": bullish * 25
            }

        if bearish >= 2:
            return {
                "trend": "BEARISH",
                "strength": bearish,
                "score": bearish * 25
            }

        return {
            "trend": "RANGE",
            "strength": 0,
            "score": 0
        }
