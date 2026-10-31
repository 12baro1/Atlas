"""
liquidity_sweep_engine.py
Atlas SMC Engine
"""


class LiquiditySweepEngine:
    """Detect unconsumed liquidity sweeps and later, causally confirmed reversals."""

    CONFIRMATION_LOOKBACK_BARS = 8

    def detect(self, candles, structure=None, liquidity_layers=None, timeframe="15m"):
        candles = candles or []
        structure = structure if isinstance(structure, list) else []
        layers = liquidity_layers if isinstance(liquidity_layers, dict) else {}
        if len(candles) < 3:
            return self._empty_result(timeframe)

        swing_levels = layers.get("swing", [])
        internal_levels = layers.get("internal", [])
        has_reference_levels = bool(swing_levels or internal_levels)

        candidate = self._find_recent_sweep(candles, swing_levels, internal_levels)
        if candidate:
            buy_event = candidate.get("buy_event")
            sell_event = candidate.get("sell_event")
            sweep_index = candidate["sweep_index"]
            active_side = candidate["side"]
            post_structure = self._post_structure_confirmation(
                structure=structure,
                candles=candles,
                sweep_index=sweep_index,
                swept_side=active_side,
            )
            strength = self._strength_score(
                buy_event, sell_event, post_structure, timeframe
            )
            return {
                "buy_side": bool(buy_event and buy_event.get("is_sweep")),
                "sell_side": bool(sell_event and sell_event.get("is_sweep")),
                "swept_high": buy_event["level"] if buy_event else None,
                "swept_low": sell_event["level"] if sell_event else None,
                "breakout_high": None,
                "breakout_low": None,
                "is_sweep": True,
                "is_breakout": False,
                "strength_score": strength,
                "swing": {
                    "buy_side": candidate.get("swing_buy"),
                    "sell_side": candidate.get("swing_sell"),
                },
                "internal": {
                    "buy_side": candidate.get("internal_buy"),
                    "sell_side": candidate.get("internal_sell"),
                },
                "post_structure": post_structure,
                "timeframe": timeframe,
                "sweep_index": sweep_index,
                "sweep_age_bars": len(candles) - 1 - sweep_index,
                "sweep_level": candidate.get("level"),
                "sweep_side": active_side,
            }

        # Legacy fallback is retained only if no actual liquidity references
        # exist. It is deliberately limited to the latest candle and cannot
        # confirm a market entry because it has no formed liquidity pool.
        if not has_reference_levels:
            prev, last = candles[-2], candles[-1]
            buy_side = last.high > prev.high and last.close < prev.high
            sell_side = last.low < prev.low and last.close > prev.low
            if buy_side or sell_side:
                return {
                    "buy_side": buy_side,
                    "sell_side": sell_side,
                    "swept_high": prev.high if buy_side else None,
                    "swept_low": prev.low if sell_side else None,
                    "breakout_high": None,
                    "breakout_low": None,
                    "is_sweep": True,
                    "is_breakout": False,
                    "strength_score": 55,
                    "swing": {"buy_side": None, "sell_side": None},
                    "internal": {"buy_side": None, "sell_side": None},
                    "post_structure": {
                        "confirmed": False,
                        "type": None,
                        "direction": None,
                        "reason": "legacy_fallback_has_no_pool",
                    },
                    "timeframe": timeframe,
                    "sweep_index": len(candles) - 1,
                    "sweep_age_bars": 0,
                    "sweep_level": prev.high if buy_side else prev.low,
                    "sweep_side": "BUY_SIDE" if buy_side else "SELL_SIDE",
                }

        return self._empty_result(timeframe)

    def _empty_result(self, timeframe):
        return {
            "buy_side": False,
            "sell_side": False,
            "swept_high": None,
            "swept_low": None,
            "breakout_high": None,
            "breakout_low": None,
            "is_sweep": False,
            "is_breakout": False,
            "strength_score": 0,
            "swing": {"buy_side": None, "sell_side": None},
            "internal": {"buy_side": None, "sell_side": None},
            "post_structure": {"confirmed": False, "type": None, "direction": None},
            "timeframe": timeframe,
            "sweep_index": None,
            "sweep_age_bars": None,
            "sweep_level": None,
            "sweep_side": None,
        }

    def _find_recent_sweep(self, candles, swing_levels, internal_levels):
        start = max(1, len(candles) - self.CONFIRMATION_LOOKBACK_BARS)
        for sweep_index in range(len(candles) - 1, start - 1, -1):
            previous = candles[sweep_index - 1]
            current = candles[sweep_index]

            eligible_swing = [
                item for item in swing_levels
                if self._level_available_and_unconsumed(
                    candles, item, sweep_index
                )
            ]
            eligible_internal = [
                item for item in internal_levels
                if self._level_available_and_unconsumed(
                    candles, item, sweep_index
                )
            ]

            swing_buy, swing_sell = self._nearest_levels(eligible_swing, previous)
            internal_buy, internal_sell = self._nearest_levels(eligible_internal, previous)

            buy_ref = swing_buy or internal_buy
            sell_ref = swing_sell or internal_sell
            buy_event = self._classify_side("BUY_SIDE", current, buy_ref)
            sell_event = self._classify_side("SELL_SIDE", current, sell_ref)

            buy_swept = bool(buy_event and buy_event["is_sweep"])
            sell_swept = bool(sell_event and sell_event["is_sweep"])
            if not buy_swept and not sell_swept:
                continue

            if buy_swept and sell_swept:
                return {
                    "sweep_index": sweep_index,
                    "side": "DUAL",
                    "level": None,
                    "buy_event": buy_event,
                    "sell_event": sell_event,
                    "swing_buy": swing_buy,
                    "swing_sell": swing_sell,
                    "internal_buy": internal_buy,
                    "internal_sell": internal_sell,
                }

            event = buy_event if buy_swept else sell_event
            swept_side = "BUY_SIDE" if buy_swept else "SELL_SIDE"
            if self._sweep_reclaimed_after_event(
                candles, sweep_index, float(event["level"]), swept_side
            ):
                continue
            return {
                "sweep_index": sweep_index,
                "side": swept_side,
                "level": event["level"],
                "buy_event": buy_event if buy_swept else None,
                "sell_event": sell_event if sell_swept else None,
                "swing_buy": swing_buy,
                "swing_sell": swing_sell,
                "internal_buy": internal_buy,
                "internal_sell": internal_sell,
            }
        return None

    def _sweep_reclaimed_after_event(self, candles, sweep_index, level, swept_side):
        """A later close back through the swept pool invalidates the old reversal."""
        for candle in candles[sweep_index + 1:]:
            close = float(candle.close)
            if swept_side == "BUY_SIDE" and close >= level:
                return True
            if swept_side == "SELL_SIDE" and close <= level:
                return True
        return False

    def _level_available_and_unconsumed(self, candles, level, sweep_index):
        try:
            price = float(level.get("price", 0))
            formed_at = int(level.get("formed_at", -1))
            price_formed_at = int(level.get("price_formed_at", formed_at))
        except (TypeError, ValueError, AttributeError):
            return False
        available_at = max(formed_at, price_formed_at)
        if price <= 0 or available_at >= sweep_index:
            return False

        side = level.get("type")
        # Start at the first touch, not only at the time the cluster becomes
        # confirmed. A wick-through while the pool is still forming also
        # consumes the would-be equal-high/low liquidity.
        try:
            touch_indices = [int(value) for value in (level.get("indices") or [])]
        except (TypeError, ValueError, OverflowError):
            return False
        first_touch = min(touch_indices) if touch_indices else max(0, formed_at)
        for candle in candles[first_touch:sweep_index]:
            if side == "BUY_SIDE" and float(candle.high) > price:
                return False
            if side == "SELL_SIDE" and float(candle.low) < price:
                return False
        return side in {"BUY_SIDE", "SELL_SIDE"}

    def detect_multi(self, timeframe_data):
        results = {}
        for timeframe, payload in timeframe_data.items():
            candles = payload.get("candles") or []
            structure = payload.get("structure") or []
            liquidity_layers = payload.get("liquidity_layers") or {}
            results[timeframe] = self.detect(
                candles=candles,
                structure=structure,
                liquidity_layers=liquidity_layers,
                timeframe=timeframe,
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
        buy = min(
            buy_candidates,
            key=lambda item: float(item["price"]) - reference_price,
            default=None,
        )
        sell = min(
            sell_candidates,
            key=lambda item: reference_price - float(item["price"]),
            default=None,
        )
        return buy, sell

    def _classify_side(self, side, candle, reference):
        if reference is None:
            return None
        level = float(reference["price"])
        if side == "BUY_SIDE":
            if candle.high <= level:
                return None
            is_sweep = candle.close < level
            return {
                "side": side,
                "level": level,
                "is_sweep": is_sweep,
                "is_breakout": not is_sweep,
                "penetration": max(0.0, float(candle.high) - level),
                "touches": reference.get("touches", 1),
                "liquidity_kind": reference.get("liquidity_kind", "SWING"),
            }

        if candle.low >= level:
            return None
        is_sweep = candle.close > level
        return {
            "side": side,
            "level": level,
            "is_sweep": is_sweep,
            "is_breakout": not is_sweep,
            "penetration": max(0.0, level - float(candle.low)),
            "touches": reference.get("touches", 1),
            "liquidity_kind": reference.get("liquidity_kind", "SWING"),
        }

    def _post_structure_confirmation(self, structure, candles, sweep_index, swept_side):
        if swept_side == "DUAL":
            return {
                "confirmed": False,
                "type": None,
                "direction": None,
                "reason": "dual_sweep_ambiguous",
            }

        trigger = "BEARISH" if swept_side == "BUY_SIDE" else "BULLISH"
        current_index = len(candles) - 1
        candidates = []

        # 15m mini structure: a one-left/one-right pivot must form AFTER
        # the sweep. The pivot is observable only after its right candle closes.
        for pivot_index in range(max(1, sweep_index + 1), current_index):
            left = candles[pivot_index - 1]
            pivot = candles[pivot_index]
            right = candles[pivot_index + 1]
            if trigger == "BEARISH":
                is_pivot = pivot.low < left.low and pivot.low < right.low
                level = float(pivot.low)
            else:
                is_pivot = pivot.high > left.high and pivot.high > right.high
                level = float(pivot.high)
            if not is_pivot:
                continue

            pivot_confirmation_index = pivot_index + 1
            # The close must break the already-confirmed post-sweep pivot.
            for break_index in range(pivot_confirmation_index + 1, len(candles)):
                previous_close = float(candles[break_index - 1].close)
                current_close = float(candles[break_index].close)
                if trigger == "BEARISH":
                    crossed = previous_close >= level and current_close < level
                else:
                    crossed = previous_close <= level and current_close > level
                if crossed:
                    candidates.append((break_index, pivot_confirmation_index, pivot_index, level))
                    break

        if not candidates:
            return {
                "confirmed": False,
                "type": None,
                "direction": trigger,
                "reason": "post_sweep_structure_break_missing",
                "sweep_index": sweep_index,
            }

        break_index, pivot_confirmation_index, pivot_index, level = min(
            candidates, key=lambda item: item[0]
        )
        return {
            "confirmed": True,
            "type": "CHOCH",
            "direction": trigger,
            "confirmation_index": break_index,
            "confirmation_age_bars": current_index - break_index,
            "pivot_index": pivot_index,
            "pivot_confirmation_index": pivot_confirmation_index,
            "broken_level": level,
            "sweep_index": sweep_index,
            "reason": "confirmed_close_through_post_sweep_mini_swing",
        }

    def _strength_score(self, buy_side_event, sell_side_event, post_structure, timeframe):
        event = buy_side_event or sell_side_event
        if event is None:
            return 0
        timeframe_bonus = {"15m": 0, "1h": 6, "4h": 10, "1d": 14}.get(timeframe, 0)
        touch_bonus = min(event.get("touches", 1) * 4, 20)
        penetration_bonus = min(int(event.get("penetration", 0) * 1000), 20)
        structure_bonus = 20 if post_structure.get("confirmed") else 0
        kind_bonus = 8 if event.get("liquidity_kind") == "SWING" else 4
        score = 40 + timeframe_bonus + touch_bonus + penetration_bonus + structure_bonus + kind_bonus
        return max(0, min(100, score))
