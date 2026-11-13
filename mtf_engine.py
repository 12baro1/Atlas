"""Multi-timeframe market structure direction.

The trading hierarchy is weekly context -> 4H directional structure -> 15m
execution confirmation. Daily structure is retained as context, not as an
equal vote that can cancel a valid 4H direction.
"""


class MTFEngine:

    @staticmethod
    def _trend_from_structure(structure, allow_recent_break=False):
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

        # On 4H, the latest confirmed directional break is authoritative until
        # a newer opposing BOS/CHoCH appears. Do not expire it merely because
        # ordinary swing labels were appended: list position is not elapsed time.
        # This also prevents an older HH+HL/LH+LL pair from overriding a newer
        # opposing structural break.
        if allow_recent_break:
            events = [
                item for item in structure
                if isinstance(item, dict)
                and (item.get("bos") or item.get("choch"))
                and str(item.get("direction", "")).upper() in {"BULLISH", "BEARISH"}
            ]
            if events:
                latest = events[-1]
                return str(latest.get("direction", "")).upper()

        # Weekly/daily (and 4H without a confirmed break event) retain the
        # stricter complete swing-sequence requirement.
        if last_high == "HH" and last_low == "HL":
            return "BULLISH"
        if last_high == "LH" and last_low == "LL":
            return "BEARISH"

        return "NEUTRAL"

    @staticmethod
    def _confirmed_ltf_reversal(liquidity_sweep):
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

        # The sweep engine's post_structure is the causal event ledger: it
        # only emits confirmation after a pivot formed after the sweep and a
        # later candle closed through it. Do not require the unrelated latest
        # CHoCH label from the general structure list; that event may predate
        # this sweep or refer to a different swing.
        event_type = str(post.get("type") or "").upper()
        if event_type and event_type != "CHOCH":
            return None
        sweep_index = post.get("sweep_index", liquidity_sweep.get("sweep_index"))
        confirmation_index = post.get("confirmation_index")
        if sweep_index is None or confirmation_index is None:
            return None
        try:
            if int(confirmation_index) <= int(sweep_index):
                return None
        except (TypeError, ValueError, OverflowError):
            return None
        return direction

    def detect(self, weekly, daily, h4, entry, liquidity_sweep=None):
        weekly_trend = self._trend_from_structure(weekly)
        daily_trend = self._trend_from_structure(daily)
        h4_trend = self._trend_from_structure(h4, allow_recent_break=True)

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

        # A fully confirmed 15m sweep/reclaim/CHoCH may reverse the 4H
        # direction. The reversal exception is evaluated before the 4H trend
        # fallback so the downstream HTF/LTF quality filter can recognize it.
        reversal = self._confirmed_ltf_reversal(liquidity_sweep)
        if reversal in {"LONG", "SHORT"}:
            entry_signal = reversal
            entry_source = "CONFIRMED_15M_REVERSAL"
            direction_reason = (
                "confirmed_15m_reversal_against_h4"
                if h4_trend in {"BULLISH", "BEARISH"}
                and reversal != ("LONG" if h4_trend == "BULLISH" else "SHORT")
                else "confirmed_15m_reversal_weekly_countertrend"
                if weekly_trend in {"BULLISH", "BEARISH"}
                and reversal != ("LONG" if weekly_trend == "BULLISH" else "SHORT")
                else "confirmed_15m_reversal"
            )
        elif h4_trend == "BULLISH":
            # Weekly/daily disagreement is context, not a second directional veto.
            entry_signal = "LONG"
            entry_source = "H4_STRUCTURE"
            direction_reason = "h4_bullish_weekly_countertrend" if weekly_h4_conflict else "h4_bullish"
        elif h4_trend == "BEARISH":
            entry_signal = "SHORT"
            entry_source = "H4_STRUCTURE"
            direction_reason = "h4_bearish_weekly_countertrend" if weekly_h4_conflict else "h4_bearish"

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
