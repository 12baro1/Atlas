"""
trend_engine.py
Atlas Trend Engine
"""

class TrendEngine:

    def detect(self, weekly, daily, h4):

        score = 0

        if weekly:
            label = weekly[-1]["label"]
            if label in ["HH", "HL"]:
                score += 1
            elif label in ["LL", "LH"]:
                score -= 1

        if daily:
            label = daily[-1]["label"]
            if label in ["HH", "HL"]:
                score += 1
            elif label in ["LL", "LH"]:
                score -= 1

        if h4:
            label = h4[-1]["label"]
            if label in ["HH", "HL"]:
                score += 1
            elif label in ["LL", "LH"]:
                score -= 1

        if score >= 2:
            return "BULLISH"

        if score <= -2:
            return "BEARISH"

        return "RANGE"
