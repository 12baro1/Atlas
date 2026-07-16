"""
fvg_engine.py
Atlas SMC Engine
"""

class FVGEngine:

    def detect(self, candles):

        gaps = []

        for i in range(2, len(candles)):

            c1 = candles[i - 2]
            c2 = candles[i - 1]
            c3 = candles[i]

            if c1.high < c3.low:
                gaps.append({
                    "type": "BULLISH",
                    "from": c1.high,
                    "to": c3.low,
                    "index": i,
                    "filled": False
                })

            elif c1.low > c3.high:
                gaps.append({
                    "type": "BEARISH",
                    "from": c3.high,
                    "to": c1.low,
                    "index": i,
                    "filled": False
                })

        return gaps
