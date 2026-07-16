"""
liquidity_engine.py
Atlas SMC Engine
"""

class LiquidityEngine:

    def detect(self, structure, tolerance=0.001):

        zones = []

        highs = []
        lows = []

        for item in structure:

            if item["kind"] == "HIGH":

                matched = False

                for level in highs:
                    if abs(level["price"] - item["price"]) / level["price"] <= tolerance:
                        level["touches"] += 1
                        matched = True
                        break

                if not matched:
                    highs.append({
                        "price": item["price"],
                        "touches": 1,
                        "type": "BUY_SIDE"
                    })

            else:

                matched = False

                for level in lows:
                    if abs(level["price"] - item["price"]) / level["price"] <= tolerance:
                        level["touches"] += 1
                        matched = True
                        break

                if not matched:
                    lows.append({
                        "price": item["price"],
                        "touches": 1,
                        "type": "SELL_SIDE"
                    })

        for level in highs + lows:
            if level["touches"] >= 2:
                zones.append(level)

        return zones
