"""Multi-timeframe market structure direction.

The trading hierarchy is weekly context -> 4H directional structure -> 15m
execution confirmation. Daily structure is retained as context, not as an
equal vote that can cancel a valid 4H direction.
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

    @staticmethod
    def _confirmed_ltf_reversal(structure, liquidity_sweep):
        """Require a directional sweep reclaim followed by a closed 15m CHoCH."""
        if not isinstance(liquidity_sweep, dict) or not liquidity_sweep.get("is_sweep"):
            return None

        post = liquidity_sweep.get("post_structure")
        if not isinstance(post, dict) or not post.get("confirmed"):
            return None

        side = str(liquidity_sweep.get("sweep_side", "")).upper()
        if side == "SELL_SIDE":
            direction, expected = "LONG", "BULLISH"
        elif side == "BUY_SIDE":
            direction, expected = "SHORT", "BEARISH"
        else:
            if liquidity_sweep.get("sell_side") and not liquidity_sweep.get("buy_side"):
                direction, expected = "LONG", "BULLISH"
            elif liquidity_sweep.get("buy_side") and not liquidity_sweep.get("sell_side"):
                direction, expected = "SHORT", "BEARISH"
            else:
                return None

        if str(post.get("direction", "")).upper() != expected:
            return None

        events = [
            item for item in (structure or [])
            if isinstance(item, dict) and item.get("choch")
        ]
        if not events:
            return None

        latest = events[-1]
        label = str(latest.get("label", "")).upper()
        event_direction = str(latest.get("direction", "")).upper()
        if event_direction != expected:
            return None
        if direction == "LONG" and label != "HH":
            return None
        if direction == "SHORT" and label != "LL":
            return None
        return direction

    def detect(self, weekly, daily, h4, entry, liquidity_sweep=None):
        weekly_trend = self._trend_from_structure(weekly)
        daily_trend = self._trend_from_structure(daily)
        h4_trend = self._trend_from_structure(h4)

        trends = [weekly_trend, daily_trend, h4_trend]
        bulls = trends.count("BULLISH")
        bears = trends.count("BEARISH")
        weekly_h4_conflict = (
            weekly_trend in {"BULLISH", "BEARISH"}
            and h4_trend in {"BULLISH", "BEARISH"}
            and weekly_trend != h4_trend
        )
        daily_h4_conflict = (
            daily_trend in {"BULLISH", "BEARISH"}
            and h4_trend in {"BULLISH", "BEARISH"}
            and daily_trend != h4_trend
        )

        entry_signal = "NONE"
        entry_source = "NONE"
        direction_reason = "h4_structure_neutral"

        # 4H is the primary directional timeframe. A genuine weekly conflict
        # blocks the setup; daily disagreement is reported as context only.
        if h4_trend == "BULLISH" and not weekly_h4_conflict:
            entry_signal = "LONG"
            entry_source = "H4_STRUCTURE"
            direction_reason = "h4_bullish"
        elif h4_trend == "BEARISH" and not weekly_h4_conflict:
            entry_signal = "SHORT"
            entry_source = "H4_STRUCTURE"
            direction_reason = "h4_bearish"
        elif weekly_h4_conflict:
            direction_reason = "weekly_h4_conflict"
        else:
            # 15m can establish direction only when 4H is neutral. It still
            # requires a real liquidity sweep, post-sweep reclaim and CHoCH.
            reversal = self._confirmed_ltf_reversal(entry, liquidity_sweep)
            if reversal == "LONG" and weekly_trend != "BEARISH":
                entry_signal = reversal
                entry_source = "CONFIRMED_15M_REVERSAL"
                direction_reason = "confirmed_15m_reversal"
            elif reversal == "SHORT" and weekly_trend != "BULLISH":
                entry_signal = reversal
                entry_source = "CONFIRMED_15M_REVERSAL"
                direction_reason = "confirmed_15m_reversal"

        return {
            "trend": weekly_trend,
            "weekly": weekly_trend,
            "daily": daily_trend,
            "h4": h4_trend,
            "entry": entry_signal,
            "entry_source": entry_source,
            "direction_reason": direction_reason,
            "weekly_h4_conflict": weekly_h4_conflict,
            "daily_h4_conflict": daily_h4_conflict,
            "valid": entry_signal != "NONE",
            "bullish_timeframes": bulls,
            "bearish_timeframes": bears,
            "neutral_timeframes": 3 - bulls - bears,
        }
