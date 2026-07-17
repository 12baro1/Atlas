"""
dynamic_tp_engine.py
Atlas Dynamic TP Engine
"""

class DynamicTPEngine:

    def calculate(
        self,
        direction,
        entry,
        liquidity,
        fvg,
        orderblocks
    ):

        targets = []

        if direction == "LONG":

            for item in liquidity:
                if item["price"] > entry:
                    targets.append(item["price"])

            for item in fvg:
                if item["to"] > entry:
                    targets.append(item["to"])

            for item in orderblocks:
                if item["high"] > entry:
                    targets.append(item["high"])

            targets = sorted(set(targets))

        else:

            for item in liquidity:
                if item["price"] < entry:
                    targets.append(item["price"])

            for item in fvg:
                if item["from"] < entry:
                    targets.append(item["from"])

            for item in orderblocks:
                if item["low"] < entry:
                    targets.append(item["low"])

            targets = sorted(set(targets), reverse=True)

        while len(targets) < 3:
            targets.append(None)

        return {
            "tp1": targets[0],
            "tp2": targets[1],
            "tp3": targets[2]
        }
