"""
rr_engine.py
Atlas SMC Engine v3
"""

import math

class RREngine:

    def calculate_rr(self, entry, stop_loss, tp3):
        if entry is None or stop_loss is None or tp3 is None:
            return None

        risk = abs(entry - stop_loss)
        if risk <= 0:
            return None

        reward = abs(tp3 - entry)
        rr = reward / risk
        if not math.isfinite(rr):
            return None

        return round(rr, 2)

    def evaluate(self, risk):

        if risk is None:
            return None

        rr = risk.get("rr")

        if rr is None:
            rr = self.calculate_rr(
                risk.get("entry"),
                risk.get("stop_loss"),
                risk.get("tp3"),
            )

        if rr is not None:
            try:
                rr = round(float(rr), 2)
            except (TypeError, ValueError):
                rr = None

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

            "entry": risk.get("entry"),

            "stop_loss": risk.get("stop_loss"),

            "tp1": risk.get("tp1"),

            "tp2": risk.get("tp2"),

            "tp3": risk.get("tp3"),

            "position_size": risk.get("position_size"),

            "capital_at_risk": risk.get("capital_at_risk")

        }
