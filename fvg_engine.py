"""
fvg_engine.py
Atlas SMC Engine
"""

class FVGEngine:
    """
    Fair Value Gap (v1)

    Bullish FVG:
        candle1.high < candle3.low

    Bearish FVG:
        candle1.low > candle3.high
    """

    def detect(self, candles):

        gaps = []

        if len(candles) < 3:
            return gaps

        for i in range(2, len(candles)):

            c1 = candles[i - 2]
            c2 = candles[i - 1]
            c3 = candles[i]

            # Bullish FVG
            if c1.high < c3.low:
                gaps.append({
                    "type": "BULLISH",
                    "index": i,
                    "top": c3.low,
                    "bottom": c1.high,
                    "filled": False
                })

            # Bearish FVG
            elif c1.low > c3.high:
                gaps.append({
                    "type": "BEARISH",
                    "index": i,
                    "top": c1.low,
                    "bottom": c3.high,
                    "filled": False
                })

        return gaps
