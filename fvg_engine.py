"""
fvg_engine.py
Atlas SMC Engine
"""

class FVGEngine:

    def detect(self, candles):

        gaps = []

        for i in range(2, len(candles)):

            c1 = candles[i - 2]
            c3 = candles[i]

            # Bullish FVG
            if c1.high < c3.low:

                filled = False

                for c in candles[i + 1:]:

                    if c.low <= c1.high:
                        filled = True
                        break

                gaps.append({
                    "type": "BULLISH",
                    "from": c1.high,
                    "to": c3.low,
                    "index": i,
                    "filled": filled
                })

            # Bearish FVG
            elif c1.low > c3.high:

                filled = False

                for c in candles[i + 1:]:

                    if c.high >= c1.low:
                        filled = True
                        break

                gaps.append({
                    "type": "BEARISH",
                    "from": c3.high,
                    "to": c1.low,
                    "index": i,
                    "filled": filled
                })

        # Sadece aktif FVG'leri döndür
        return [gap for gap in gaps if not gap["filled"]]
