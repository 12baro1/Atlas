"""
trend_engine.py
Atlas Trend Engine v6
Trend, ilgili zaman diliminin kendi onaylı yapısından hesaplanır.
"""


class TrendEngine:

    def calculate(self, mtf, structure=None):
        mtf = mtf if isinstance(mtf, dict) else {}
        direction = "NONE"
        source = "mtf_fallback"

        if structure is not None:
            source = "structure"
            for item in reversed(structure or []):
                if not isinstance(item, dict) or not (item.get("bos") or item.get("choch")):
                    continue
                candidate = str(item.get("direction", "")).upper()
                if candidate in {"BULLISH", "BEARISH"}:
                    direction = candidate
                    break
            if direction == "NONE":
                labels = [
                    str(item.get("label", "")).upper()
                    for item in (structure or []) if isinstance(item, dict)
                ][-6:]
                bullish = sum(label in {"HH", "HL"} for label in labels)
                bearish = sum(label in {"LH", "LL"} for label in labels)
                if bullish >= 2 and bullish > bearish:
                    direction = "BULLISH"
                elif bearish >= 2 and bearish > bullish:
                    direction = "BEARISH"
        else:
            entry = str(mtf.get("entry", "NONE")).upper()
            direction = "BULLISH" if entry == "LONG" else "BEARISH" if entry == "SHORT" else "NONE"

        if direction in {"BULLISH", "BEARISH"}:
            weekly = str(mtf.get("weekly", "NEUTRAL")).upper()
            strength = 3 if weekly == direction else 2
            return {
                "trend": direction, "strength": strength, "score": strength * 25,
                "source": "h4_structure" if source == "structure" else source,
                "derived_from": "h4_structure" if source == "structure" else "mtf_entry",
                "independent": False,
            }
        return {
            "trend": "RANGE", "strength": 0, "score": 0,
            "source": "h4_structure" if source == "structure" else source,
            "derived_from": "h4_structure" if source == "structure" else "mtf_entry",
            "independent": False,
        }
