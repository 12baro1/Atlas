"""
bos_engine.py
Atlas SMC Engine
"""

class BOSEngine:

    def detect(self, pivots):

        structure = []

        if len(pivots) < 4:
            return structure

        last_high = None
        last_low = None

        for pivot in pivots:

            event = {
                "index": pivot["index"],
                "price": pivot["price"],
                "kind": pivot["type"],
                "label": pivot["label"],
                "bos": False,
                "direction": None
            }

            if pivot["type"] == "HIGH":

                if last_high is None:
                    last_high = pivot
                else:
                    if pivot["price"] > last_high["price"]:
                        event["bos"] = True
                        event["direction"] = "BULLISH"
                    last_high = pivot

            else:

                if last_low is None:
                    last_low = pivot
                else:
                    if pivot["price"] < last_low["price"]:
                        event["bos"] = True
                        event["direction"] = "BEARISH"
                    last_low = pivot

            structure.append(event)

        return structure
