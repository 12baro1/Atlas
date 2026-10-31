"""
liquidity_sweep_engine.py
Atlas SMC Engine
"""


class LiquiditySweepEngine:
    """Detect buy-side and sell-side liquidity sweeps."""

    def detect(self, candles, structure=None, liquidity_layers=None, timeframe="15m"):
        if len(candles) < 3:
            return {
                "buy_side": False, "sell_side": False,
                "swept_high": None, "swept_low": None,
                "breakout_high": None, "breakout_low": None,
                "is_sweep": False, "is_breakout": False,
                "strength_score": 0,
                "swing": {"buy_side": None, "sell_side": None},
                "internal": {"buy_side": None, "sell_side": None},
                "post_structure": {"confirmed": False, "type": None, "direction": None},
                "timeframe": timeframe,
            }

        prev, last = candles[-2], candles[-1]
        structure = structure or []
        layers = liquidity_layers or {"swing": [], "internal": [], "all": []}

        # Liquidity must remain untouched before the current candle. A prior
        # wick through a level consumes that reference even when the candle
        # closes back on the original side; otherwise the same pool can be
        # counted as a fresh sweep more than once.
        swing_levels = layers.get("swing", [])
        internal_levels = layers.get("internal", [])
        has_reference_levels = bool(swing_levels or internal_levels)
        swing_buy, swing_sell = self._nearest_levels(swing_levels, prev)
        internal_buy, internal_sell = self._nearest_levels(internal_levels, prev)

        buy_side_event = self._classify_side("BUY_SIDE", last, swing_buy or internal_buy)
        sell_side_event = self._classify_side("SELL_SIDE", last, swing_sell or internal_sell)
        post_structure = self._post_structure_confirmation(
            structure, buy_side_event, sell_side_event, sweep_index=len(candles) - 1, current_index=len(candles) - 1
        )
        strength = self._strength_score(buy_side_event, sell_side_event, post_structure, timeframe)

        buy_side = buy_side_event["is_sweep"] if buy_side_event else False
        sell_side = sell_side_event["is_sweep"] if sell_side_event else False
        breakout_high = buy_side_event["level"] if buy_side_event and buy_side_event["is_breakout"] else None
        breakout_low = sell_side_event["level"] if sell_side_event and sell_side_event["is_breakout"] else None

        # Legacy fallback is only safe when no liquidity references were
        # supplied. Do not re-label a previously swept reference as a new
        # previous-candle high/low sweep after it has been filtered out.
        if not has_reference_levels and buy_side_event is None and sell_side_event is None:
            buy_side = last.high > prev.high and last.close < prev.high
            sell_side = last.low < prev.low and last.close > prev.low
            strength = 55 if buy_side or sell_side else 0

        return {
            "buy_side": buy_side,
            "sell_side": sell_side,
            "swept_high": buy_side_event["level"] if buy_side_event and buy_side_event["is_sweep"] else prev.high if buy_side else None,
            "swept_low": sell_side_event["level"] if sell_side_event and sell_side_event["is_sweep"] else prev.low if sell_side else None,
            "breakout_high": breakout_high,
            "breakout_low": breakout_low,
            "is_sweep": buy_side or sell_side,
            "is_breakout": breakout_high is not None or breakout_low is not None,
            "strength_score": strength,
            "swing": {"buy_side": swing_buy, "sell_side": swing_sell},
            "internal": {"buy_side": internal_buy, "sell_side": internal_sell},
            "post_structure": post_structure,
            "timeframe": timeframe,
        }

    def detect_multi(self, timeframe_data):
        results = {}
        for timeframe, payload in timeframe_data.items():
            candles = payload.get("candles") or []
            structure = payload.get("structure") or []
            liquidity_layers = payload.get("liquidity_layers") or {}
            results[timeframe] = self.detect(
                candles=candles, structure=structure,
                liquidity_layers=liquidity_layers, timeframe=timeframe,
            )

        active = [item for item in results.values() if item.get("is_sweep")]
        best = max(active, key=lambda item: item.get("strength_score", 0)) if active else None
        return {"timeframes": results, "active": bool(active), "best": best}

    def _nearest_levels(self, levels, reference_candle):
        reference_price = float(reference_candle.close)
        previous_high = float(reference_candle.high)
        previous_low = float(reference_candle.low)
        buy_candidates = [
            item for item in levels
            if item.get("type") == "BUY_SIDE"
            and float(item.get("price", 0)) > reference_price
            and previous_high <= float(item.get("price", 0))
        ]
        sell_candidates = [
            item for item in levels
            if item.get("type") == "SELL_SIDE"
            and 0 < float(item.get("price", 0)) < reference_price
            and previous_low >= float(item.get("price", 0))
        ]
        buy = min(buy_candidates, key=lambda item: float(item["price"]) - reference_price, default=None)
        sell = min(sell_candidates, key=lambda item: reference_price - float(item["price"]), default=None)
        return buy, sell

    def _classify_side(self, side, candle, reference):
        if reference is None:
            return None
        level = reference["price"]
        if side == "BUY_SIDE":
            if candle.high <= level:
                return None
            is_sweep = candle.close < level
            return {
                "side": side, "level": level, "is_sweep": is_sweep,
                "is_breakout": not is_sweep,
                "penetration": max(0.0, candle.high - level),
                "touches": reference.get("touches", 1),
                "liquidity_kind": reference.get("liquidity_kind", "SWING"),
            }

        if candle.low >= level:
            return None
        is_sweep = candle.close > level
        return {
            "side": side, "level": level, "is_sweep": is_sweep,
            "is_breakout": not is_sweep,
            "penetration": max(0.0, level - candle.low),
            "touches": reference.get("touches", 1),
            "liquidity_kind": reference.get("liquidity_kind", "SWING"),
        }

    def _post_structure_confirmation(self, structure, buy_side_event, sell_side_event, sweep_index=None, current_index=None):
        if not structure:
            return {"confirmed": False, "type": None, "direction": None, "reason": "no_structure"}
        last = structure[-1]
        trigger = None
        if buy_side_event and buy_side_event["is_sweep"]:
            trigger = "BEARISH"
        elif sell_side_event and sell_side_event["is_sweep"]:
            trigger = "BULLISH"
        if trigger is None:
            return {"confirmed": False, "type": None, "direction": None, "reason": "no_sweep"}
        # A pivot index is not the candle on which its BOS was confirmed.
        # Require explicit post-sweep chronology; never reuse an older BOS/CHoCH.
        confirmation_index = last.get("confirmation_index", last.get("break_index"))
        try:
            confirmation_index = int(confirmation_index)
            sweep_index = int(sweep_index)
            current_index = int(current_index)
        except (TypeError, ValueError):
            return {
                "confirmed": False, "type": None, "direction": trigger,
                "reason": "chronology_unavailable",
            }
        if confirmation_index <= sweep_index:
            return {
                "confirmed": False, "type": None, "direction": trigger,
                "reason": "structure_not_after_sweep",
            }
        if confirmation_index > current_index:
            return {
                "confirmed": False, "type": None, "direction": trigger,
                "reason": "confirmation_not_observed_yet",
            }
        if last.get("choch") and last.get("direction") == trigger:
            return {"confirmed": True, "type": "CHOCH", "direction": trigger, "confirmation_index": confirmation_index}
        if last.get("bos") and last.get("direction") == trigger:
            return {"confirmed": True, "type": "BOS", "direction": trigger, "confirmation_index": confirmation_index}
        return {"confirmed": False, "type": None, "direction": trigger, "reason": "directional_break_missing"}

    def _strength_score(self, buy_side_event, sell_side_event, post_structure, timeframe):
        event = None
        if buy_side_event and buy_side_event["is_sweep"]:
            event = buy_side_event
        elif sell_side_event and sell_side_event["is_sweep"]:
            event = sell_side_event
        if event is None:
            return 0
        timeframe_bonus = {"15m": 0, "1h": 6, "4h": 10, "1d": 14}.get(timeframe, 0)
        touch_bonus = min(event.get("touches", 1) * 4, 20)
        penetration_bonus = min(int(event.get("penetration", 0) * 1000), 20)
        structure_bonus = 20 if post_structure.get("confirmed") else 0
        kind_bonus = 8 if event.get("liquidity_kind") == "SWING" else 4
        score = 40 + timeframe_bonus + touch_bonus + penetration_bonus + structure_bonus + kind_bonus
        return max(0, min(100, score))
