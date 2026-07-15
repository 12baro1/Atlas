"""
choch_engine.py
Atlas SMC Engine
"""

class CHOCHEngine:

    def detect(self, structure):

        if len(structure) < 4:
            return structure

        for item in structure:
            item["choch"] = False

        for i in range(3, len(structure)):

            a = structure[i - 3]
            b = structure[i - 2]
            c = structure[i - 1]
            d = structure[i]

            # Bearish -> Bullish dönüş
            if (
                a["label"] == "LL"
                and b["label"] == "LH"
                and c["label"] == "HL"
                and d["label"] == "HH"
            ):
                d["choch"] = True
                d["direction"] = "BULLISH"

            # Bullish -> Bearish dönüş
            elif (
                a["label"] == "HH"
                and b["label"] == "HL"
                and c["label"] == "LH"
                and d["label"] == "LL"
            ):
                d["choch"] = True
                d["direction"] = "BEARISH"

        return structure
