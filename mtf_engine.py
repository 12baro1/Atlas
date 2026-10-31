"""Multi-timeframe market structure direction.

A single last swing is not enough to establish trend: a bullish trend needs
both a higher high and a higher low; bearish needs a lower high and lower low.
"""
class MTFEngine:

    @staticmethod
    def _trend_from_structure(structure):
        if not isinstance(structure, (list, tuple)) or not structure:
            return "NEUTRAL"

        last_high = None
        last_low = None
        for item in structure:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind", item.get("type", ""))).upper()
            label = str(item.get("label", "")).upper()
            if kind == "HIGH" or label in {"HH", "LH", "H?"}:
                last_high = label
            elif kind == "LOW" or label in {"HL", "LL", "L?"}:
                last_low = label

        if last_high == "HH" and last_low == "HL":
            return "BULLISH"
        if last_high == "LH" and last_low == "LL":
            return "BEARISH"
        return "NEUTRAL"

    def detect(self, weekly, daily, h4, entry):
        weekly_trend = self._trend_from_structure(weekly)
        daily_trend = self._trend_from_structure(daily)
        h4_trend = self._trend_from_structure(h4)

        bulls = [weekly_trend, daily_trend, h4_trend].count("BULLISH")
        bears = [weekly_trend, daily_trend, h4_trend].count("BEARISH")

        # Conflicting/insufficient HTF evidence must not be resolved by
        # treating a single latest pivot as a complete directional trend.
        entry_signal = "NONE"
        if bulls >= 2 and bears == 0:
            entry_signal = "LONG"
        elif bears >= 2 and bulls == 0:
            entry_signal = "SHORT"

        return {
            "trend": weekly_trend,
            "weekly": weekly_trend,
            "daily": daily_trend,
            "h4": h4_trend,
            "entry": entry_signal,
            "valid": entry_signal != "NONE",
            "bullish_timeframes": bulls,
            "bearish_timeframes": bears,
            "neutral_timeframes": 3 - bulls - bears,
        }
