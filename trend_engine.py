"""
trend_engine.py
Atlas SMC Engine
"""

class TrendEngine:

    def detect(self, weekly, daily, structure):

        bullish = 0
        bearish = 0

        for item in structure[-10:]:

            label = item.get("label", "")

            if label in ["HH", "HL"]:
                bullish += 1

            elif label in ["LL", "LH"]:
                bearish += 1

        if bullish >= bearish + 2:
            return "BULLISH"

        elif bearish >= bullish + 2:
            return "BEARISH"

        return "RANGE"
