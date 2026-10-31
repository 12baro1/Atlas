"""CHoCH detection from a confirmed four-swing reversal sequence."""


class CHOCHEngine:

    @staticmethod
    def _kind(item):
        return str(item.get("kind", item.get("type", ""))).upper()

    def detect(self, structure):
        if not isinstance(structure, list):
            return structure
        if len(structure) < 4:
            for item in structure:
                item["choch"] = False
            return structure

        for item in structure:
            item["choch"] = False

        for i in range(3, len(structure)):
            a, b, c, d = structure[i - 3:i + 1]
            kinds = [self._kind(item) for item in (a, b, c, d)]
            labels = [str(item.get("label", "")).upper() for item in (a, b, c, d)]

            # Only an alternating, confirmed swing sequence can form a shift.
            if kinds not in (["LOW", "HIGH", "LOW", "HIGH"],
                             ["HIGH", "LOW", "HIGH", "LOW"]):
                continue

            # The final swing must also be a genuine structural break (BOS).
            if not bool(d.get("bos")):
                continue

            if labels == ["LL", "LH", "HL", "HH"]:
                d["choch"] = True
                d["direction"] = "BULLISH"
            elif labels == ["HH", "HL", "LH", "LL"]:
                d["choch"] = True
                d["direction"] = "BEARISH"

        return structure
