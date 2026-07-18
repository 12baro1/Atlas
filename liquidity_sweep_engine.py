"""
liquidity_sweep_engine.py
Atlas SMC Engine
"""

class LiquiditySweepEngine:
    """
    Detects buy-side and sell-side liquidity sweeps.
    """

    def detect(self, candles, structure=None, liquidity_layers=None, timeframe="15m"):

        if len(candles) < 3:
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
                "swing": {
                    "buy_side": None,
                    "sell_side": None,
                },
                "internal": {
                    "buy_side": None,
                    "sell_side": None,
                },
                "post_structure": {
                    "confirmed": False,
                    "type": None,
                    "direction": None,
                },
                "timeframe": timeframe,
            }

        prev = candles[-2]
        last = candles[-1]

        structure = structure or []
        layers = liquidity_layers or {
            "swing": [],
            "internal": [],
            "all": [],
        }

        swing_buy, swing_sell = self._nearest_levels(layers.get("swing", []), last)
        internal_buy, internal_sell = self._nearest_levels(layers.get("internal", []), last)

        buy_side_event = self._classify_side(
            side="BUY_SIDE",
            candle=last,
            reference=swing_buy or internal_buy,
        )
        sell_side_event = self._classify_side(
            side="SELL_SIDE",
            candle=last,
            reference=swing_sell or internal_sell,
        )

        post_structure = self._post_structure_confirmation(
            structure=structure,
            buy_side_event=buy_side_event,
            sell_side_event=sell_side_event,
        )

        strength = self._strength_score(
            buy_side_event=buy_side_event,
            sell_side_event=sell_side_event,
            post_structure=post_structure,
            timeframe=timeframe,
        )

        buy_side = buy_side_event["is_sweep"] if buy_side_event else False
        sell_side = sell_side_event["is_sweep"] if sell_side_event else False
        breakout_high = buy_side_event["level"] if buy_side_event and buy_side_event["is_breakout"] else None
        breakout_low = sell_side_event["level"] if sell_side_event and sell_side_event["is_breakout"] else None

        # Legacy fallback: seviye bulunamazsa son mum yaklaşımıyla sweep kontrolü.
        if buy_side_event is None and sell_side_event is None:
            buy_side = last.high > prev.high and last.close < prev.high
            sell_side = last.low < prev.low and last.close > prev.low
            strength = 55 if buy_side or sell_side else 0

        return {
            "buy_side": buy_side,
            "sell_side": sell_side,
            "swept_high": (buy_side_event["level"] if buy_side_event and buy_side_event["is_sweep"] else prev.high if buy_side else None),
            "swept_low": (sell_side_event["level"] if sell_side_event and sell_side_event["is_sweep"] else prev.low if sell_side else None),
            "breakout_high": breakout_high,
            "breakout_low": breakout_low,
            "is_sweep": buy_side or sell_side,
            "is_breakout": breakout_high is not None or breakout_low is not None,
            "strength_score": strength,
            "swing": {
                "buy_side": swing_buy,
                "sell_side": swing_sell,
            },
            "internal": {
                "buy_side": internal_buy,
                "sell_side": internal_sell,
            },
            "post_structure": post_structure,
            "timeframe": timeframe,
        }

    def detect_multi(self, timeframe_data):
        """Çoklu zaman diliminde sweep analizi döndürür."""
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

        return {
            "timeframes": results,
            "active": bool(active),
            "best": best,
        }

    def _nearest_levels(self, levels, last_candle):
        buy_candidates = [item for item in levels if item.get("type") == "BUY_SIDE"]
        sell_candidates = [item for item in levels if item.get("type") == "SELL_SIDE"]

        buy = min(
            buy_candidates,
            key=lambda item: abs(item["price"] - last_candle.high),
            default=None,
        )
        sell = min(
            sell_candidates,
            key=lambda item: abs(item["price"] - last_candle.low),
            default=None,
        )

        return buy, sell

    def _classify_side(self, side, candle, reference):
        if reference is None:
            return None

        level = reference["price"]

        if side == "BUY_SIDE":
            breached = candle.high > level
            if not breached:
                return None

            is_sweep = candle.close < level
            return {
                "side": side,
                "level": level,
                "is_sweep": is_sweep,
                "is_breakout": not is_sweep,
                "penetration": max(0.0, candle.high - level),
                "touches": reference.get("touches", 1),
                "liquidity_kind": reference.get("liquidity_kind", "SWING"),
            }

        breached = candle.low < level
        if not breached:
            return None

        is_sweep = candle.close > level
        return {
            "side": side,
            "level": level,
            "is_sweep": is_sweep,
            "is_breakout": not is_sweep,
            "penetration": max(0.0, level - candle.low),
            "touches": reference.get("touches", 1),
            "liquidity_kind": reference.get("liquidity_kind", "SWING"),
        }

    def _post_structure_confirmation(self, structure, buy_side_event, sell_side_event):
        if not structure:
            return {
                "confirmed": False,
                "type": None,
                "direction": None,
            }

        last = structure[-1]
        trigger = None

        if buy_side_event and buy_side_event["is_sweep"]:
            trigger = "BEARISH"
        elif sell_side_event and sell_side_event["is_sweep"]:
            trigger = "BULLISH"

        if trigger is None:
            return {
                "confirmed": False,
                "type": None,
                "direction": None,
            }

        if last.get("choch") and last.get("direction") == trigger:
            return {
                "confirmed": True,
                "type": "CHOCH",
                "direction": trigger,
            }

        if last.get("bos") and last.get("direction") == trigger:
            return {
                "confirmed": True,
                "type": "BOS",
                "direction": trigger,
            }

        return {
            "confirmed": False,
            "type": None,
            "direction": trigger,
        }

    def _strength_score(self, buy_side_event, sell_side_event, post_structure, timeframe):
        event = None
        if buy_side_event and buy_side_event["is_sweep"]:
            event = buy_side_event
        elif sell_side_event and sell_side_event["is_sweep"]:
            event = sell_side_event

        if event is None:
            return 0

        timeframe_bonus = {
            "15m": 0,
            "1h": 6,
            "4h": 10,
            "1d": 14,
        }.get(timeframe, 0)

        touch_bonus = min(event.get("touches", 1) * 4, 20)
        penetration_bonus = min(int(event.get("penetration", 0) * 1000), 20)
        structure_bonus = 20 if post_structure.get("confirmed") else 0
        kind_bonus = 8 if event.get("liquidity_kind") == "SWING" else 4

        score = 40 + timeframe_bonus + touch_bonus + penetration_bonus + structure_bonus + kind_bonus
        return max(0, min(100, score))
