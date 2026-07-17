"""
fvg_engine.py
Atlas FVG Engine v4
"""

class FVGEngine:

    def detect(self, candles):

        gaps = []

        if len(candles) < 3:
            return gaps

        for i in range(2, len(candles)):

            left = candles[i - 2]
            mid = candles[i - 1]
            right = candles[i]

            # -------------------------
            # Bullish FVG
            # -------------------------

            if left.high < right.low:

                size = right.low - left.high

                strength = 0

                if size > 0:
                    strength += 50

                if mid.close > mid.open:
                    strength += 20

                if right.close > right.open:
                    strength += 20

                if right.close > mid.high:
                    strength += 10

                gaps.append({
                    "type": "BULLISH",
                    "from": left.high,
                    "to": right.low,
                    "size": size,
                    "strength": strength,
                    "filled": False,
                    "index": i
                })

            # -------------------------
            # Bearish FVG
            # -------------------------

            elif left.low > right.high:

                size = left.low - right.high

                strength = 0

                if size > 0:
                    strength += 50

                if mid.close < mid.open:
                    strength += 20

                if right.close < right.open:
                    strength += 20

                if right.close < mid.low:
                    strength += 10

                gaps.append({
                    "type": "BEARISH",
                    "from": right.high,
                    "to": left.low,
                    "size": size,
                    "strength": strength,
                    "filled": False,
                    "index": i
                })

        # -------------------------
        # Mitigation Check
        # -------------------------

        for gap in gaps:

            for candle in candles[gap["index"] + 1:]:

                if candle.high >= gap["from"] and candle.low <= gap["to"]:
                    gap["filled"] = True
                    break

        return gaps
