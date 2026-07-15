class BOSEngine:
    """
    BOS (Break of Structure) Engine

    Bu modül StructureEngine tarafından üretilen HH/HL/LH/LL
    etiketlerini kullanarak BOS tespiti yapar.
    """

    def detect(self, structure):

        if len(structure) < 3:
            return structure

        for item in structure:
            item["bos"] = False
            item["direction"] = None

        for i in range(2, len(structure)):

            a = structure[i-2]
            b = structure[i-1]
            c = structure[i]

            # Bullish BOS
            if (
                a["label"] in ("HH", "H?")
                and b["label"] in ("HL", "L?")
                and c["label"] == "HH"
                and c["price"] > a["price"]
            ):
                c["bos"] = True
                c["direction"] = "BULLISH"

            # Bearish BOS
            elif (
                a["label"] in ("LL", "L?")
                and b["label"] in ("LH", "H?")
                and c["label"] == "LL"
                and c["price"] < a["price"]
            ):
                c["bos"] = True
                c["direction"] = "BEARISH"

        return structure
