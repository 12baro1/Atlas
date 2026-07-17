"""
orderblock_engine.py
Atlas Order Block Engine v4
"""

class OrderBlockEngine:

    def detect(self, candles, structure):

        blocks = []

        for item in structure:

            if not item.get("bos"):
                continue

            idx = item["index"]

            if idx <= 0 or idx >= len(candles):
                continue

            prev = candles[idx - 1]

            # -------------------------
            # Bullish Order Block
            # -------------------------

            if item["direction"] == "BULLISH":

                if prev.close < prev.open:

                    strength = 0

                    body = abs(prev.close - prev.open)
                    wick = prev.high - prev.low

                    if wick > 0:

                        body_ratio = body / wick

                        if body_ratio >= 0.70:
                            strength += 40

                        elif body_ratio >= 0.50:
                            strength += 30

                        else:
                            strength += 20

                    strength += 20

                    if item["label"] == "HH":
                        strength += 20

                    if item.get("choch"):
                        strength += 20

                    blocks.append({
                        "type": "BULLISH",
                        "index": idx - 1,
                        "high": prev.high,
                        "low": prev.low,
                        "strength": strength,
                        "mitigated": False
                    })

            # -------------------------
            # Bearish Order Block
            # -------------------------

            elif item["direction"] == "BEARISH":

                if prev.close > prev.open:

                    strength = 0

                    body = abs(prev.close - prev.open)
                    wick = prev.high - prev.low

                    if wick > 0:

                        body_ratio = body / wick

                        if body_ratio >= 0.70:
                            strength += 40

                        elif body_ratio >= 0.50:
                            strength += 30

                        else:
                            strength += 20

                    strength += 20

                    if item["label"] == "LL":
                        strength += 20

                    if item.get("choch"):
                        strength += 20

                    blocks.append({
                        "type": "BEARISH",
                        "index": idx - 1,
                        "high": prev.high,
                        "low": prev.low,
                        "strength": strength,
                        "mitigated": False
                    })

        return blocks
