"""
dynamic_tp_engine.py
Atlas Dynamic TP Engine
"""

class DynamicTPEngine:

    def calculate(
        self,
        direction,
        entry,
        stop_loss,
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

        # Likidite/FVG/OB hedefi yetersiz kaldığında RR tabanlı fallback üret.
        if stop_loss is not None:
            risk = abs(entry - stop_loss)
            if risk > 0:
                rr_targets = [1.5, 2.5, 4.0]
                for rr in rr_targets:
                    level = entry + (risk * rr) if direction == "LONG" else entry - (risk * rr)
                    targets.append(level)

        # Girdi kaynakları tekrar edebileceği için sıralamadan sonra tekilleştir.
        if direction == "LONG":
            targets = sorted(set(targets))
        else:
            targets = sorted(set(targets), reverse=True)

        while len(targets) < 3:
            targets.append(None)

        return {
            "tp1": targets[0],
            "tp2": targets[1],
            "tp3": targets[2]
        }
