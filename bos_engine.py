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
                "index": pivot.index,
                "price": pivot.price,
                "kind": pivot.kind,
                "label": "",
                "bos": False,
                "direction": None
            }

            if pivot.kind == "HIGH":

                if last_high is None:
                    event["label"] = "HH"
                    last_high = pivot
                else:
                    if pivot.price > last_high.price:
                        event["label"] = "HH"
                        event["bos"] = True
                        event["direction"] = "BULLISH"
                    else:
                        event["label"] = "LH"
                    last_high = pivot

            else:

                if last_low is None:
                    event["label"] = "LL"
                    last_low = pivot
                else:
                    if pivot.price < last_low.price:
                        event["label"] = "LL"
                        event["bos"] = True
                        event["direction"] = "BEARISH"
                    else:
                        event["label"] = "HL"
                    last_low = pivot

            structure.append(event)

        return structure
