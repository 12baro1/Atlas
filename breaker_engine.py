"""
breaker_engine.py
Atlas SMC Engine
"""

class BreakerEngine:
    """
    Breaker Block (v1)

    Bir Order Block geçersiz kaldığında
    Breaker Block olarak işaretler.
    """

    def detect(self, orderblocks, candles):

        breakers = []

        for block in orderblocks:

            high = block["high"]
            low = block["low"]
            start = block["index"] + 1

            for candle in candles[start:]:

                if block["type"] == "BULLISH":
                    if candle.close < low:
                        breakers.append({
                            "type": "BEARISH_BREAKER",
                            "high": high,
                            "low": low,
                            "origin": block["index"]
                        })
                        break

                elif block["type"] == "BEARISH":
                    if candle.close > high:
                        breakers.append({
                            "type": "BULLISH_BREAKER",
                            "high": high,
                            "low": low,
                            "origin": block["index"]
                        })
                        break

        return breakers
