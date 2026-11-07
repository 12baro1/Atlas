"""
trend_engine.py
Atlas Trend Engine v5

Trend strength follows the primary 4H direction. Weekly alignment adds
strength; daily remains contextual and cannot independently cancel direction.
"""


class TrendEngine:

    def calculate(self, mtf):
        direction = str((mtf or {}).get("entry", "NONE")).upper()
        weekly = (mtf or {}).get("weekly", "NEUTRAL")

        if direction == "LONG":
            strength = 3 if weekly == "BULLISH" else 2
            return {
                "trend": "BULLISH",
                "strength": strength,
                "score": strength * 25,
            }

        if direction == "SHORT":
            strength = 3 if weekly == "BEARISH" else 2
            return {
                "trend": "BEARISH",
                "strength": strength,
                "score": strength * 25,
            }

        return {
            "trend": "RANGE",
            "strength": 0,
            "score": 0,
        }
