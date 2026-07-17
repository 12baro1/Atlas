"""
breaker_block_engine.py
Atlas Breaker Block Engine v1
"""

class BreakerBlockEngine:

    def detect(self, candles, orderblocks):

        breakers = []

        for ob in orderblocks:

            broken = False

            for candle in candles[ob["index"] + 1:]:

                # Bullish OB kırıldı
                if (
                    ob["type"] == "BULLISH"
                    and candle.close < ob["low"]
                ):

                    broken = True

                # Bearish OB kırıldı
                elif (
                    ob["type"] == "BEARISH"
                    and candle.close > ob["high"]
                ):

                    broken = True

                if broken:

                    breakers.append({

                        "type": ob["type"],

                        "index": ob["index"],

                        "high": ob["high"],

                        "low": ob["low"],

                        "strength": ob.get("strength", 50),

                        "breaker": True

                    })

                    break

        return breakers
