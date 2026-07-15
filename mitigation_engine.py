"""
mitigation_engine.py
Atlas SMC Engine
"""

class MitigationEngine:
    """
    Mitigation (v1)

    Fiyatın Order Block, FVG veya Breaker
    bölgesine geri dönmesini tespit eder.
    """

    def check(self, candles, zones):

        mitigated = []

        for zone in zones:

            top = zone["high"]
            bottom = zone["low"]
            start = zone.get("origin", zone.get("index", 0))

            for candle in candles[start + 1:]:

                if candle.high >= bottom and candle.low <= top:

                    zone["mitigated"] = True
                    zone["mitigation_index"] = getattr(candle, "index", None)
                    mitigated.append(zone)
                    break

        return mitigated
