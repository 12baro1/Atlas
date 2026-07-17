"""
rr_engine.py
Atlas SMC Engine v3
"""

class RREngine:

    def evaluate(self, risk):

        if risk is None:
            return None

        rr = risk.get("rr")

        if rr is None:
            return None

        if rr >= 5:
            stars = "★★★★★"
            quality = "EXCELLENT"
            score = 100

        elif rr >= 4:
            stars = "★★★★☆"
            quality = "VERY GOOD"
            score = 90

        elif rr >= 3:
            stars = "★★★☆☆"
            quality = "GOOD"
            score = 80

        elif rr >= 2:
            stars = "★★☆☆☆"
            quality = "NORMAL"
            score = 65

        elif rr >= 1.5:
            stars = "★☆☆☆☆"
            quality = "WEAK"
            score = 45

        else:
            stars = "☆☆☆☆☆"
            quality = "AVOID"
            score = 20

        return {

            "rr": rr,

            "score": score,

            "quality": quality,

            "stars": stars,

            "entry": risk["entry"],

            "stop_loss": risk["stop_loss"],

            "tp1": risk["tp1"],

            "tp2": risk["tp2"],

            "tp3": risk["tp3"],

            "position_size": risk["position_size"],

            "capital_at_risk": risk["capital_at_risk"]

        }
