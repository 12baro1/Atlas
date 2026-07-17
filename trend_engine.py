"""
trend_engine.py
Atlas Trend Engine v2
"""

class TrendEngine:

    def detect(self, weekly, daily, h4):

        def direction(structure):

            if not structure:
                return "RANGE"

            bullish = 0
            bearish = 0

            for item in structure:

                if item.get("bos"):

                    if item.get("direction") == "BULLISH":
                        bullish += 1

                    elif item.get("direction") == "BEARISH":
                        bearish += 1

                if item.get("choch"):

                    if item.get("direction") == "BULLISH":
                        bullish += 2

                    elif item.get("direction") == "BEARISH":
                        bearish += 2

            if bullish > bearish:
                return "BULLISH"

            if bearish > bullish:
                return "BEARISH"

            return "RANGE"

        w = direction(weekly)
        d = direction(daily)
        h = direction(h4)

        votes = [w, d, h]

        if votes.count("BULLISH") >= 2:
            trend = "BULLISH"

        elif votes.count("BEARISH") >= 2:
            trend = "BEARISH"

        else:
            trend = "RANGE"

        return {
            "trend": trend,
            "weekly": w,
            "daily": d,
            "h4": h
        }
