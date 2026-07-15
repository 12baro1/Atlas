"""
orderblock_engine.py
Atlas SMC Engine
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

            # Bullish Order Block
            if item.get("direction") == "BULLISH":

                prev = candles[idx - 1]

                if prev.close < prev.open:
                    blocks.append({
                        "type": "BULLISH",
                        "index": idx - 1,
                        "high": prev.high,
                        "low": prev.low,
                        "mitigated": False
                    })

            # Bearish Order Block
            elif item.get("direction") == "BEARISH":

                prev = candles[idx - 1]

                if prev.close > prev.open:
                    blocks.append({
                        "type": "BEARISH",
                        "index": idx - 1,
                        "high": prev.high,
                        "low": prev.low,
                        "mitigated": False
                    })

        return blocks
