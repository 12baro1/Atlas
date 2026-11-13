"""Close-confirmed break-of-structure detection."""


class BOSEngine:
    @staticmethod
    def _value(candle, name):
        if isinstance(candle, dict):
            return float(candle[name])
        return float(getattr(candle, name))

    @staticmethod
    def _event_time_key(candles, index):
        try:
            candle = candles[int(index)]
            value = candle.get("time", candle.get("timestamp")) if isinstance(candle, dict) else getattr(candle, "time", None)
            if value is not None:
                return f"t{int(value)}"
        except (IndexError, KeyError, TypeError, ValueError, OverflowError):
            pass
        return f"i{int(index)}"

    def _close_break_index(self, candles, start, end, level, direction):
        if candles is None:
            return None
        start = max(0, int(start))
        end = min(len(candles), int(end))
        for index in range(start, end):
            try:
                close = self._value(candles[index], "close")
            except (TypeError, ValueError, KeyError, AttributeError, OverflowError):
                continue
            if direction == "BULLISH" and close > level:
                return index
            if direction == "BEARISH" and close < level:
                return index
        return None

    def detect(self, pivots, candles=None, timeframe="unknown"):
        structure = []
        if len(pivots) < 2:
            return structure

        last_high = None
        last_low = None
        for pivot in pivots:
            pivot_index = int(pivot.get("index", 0))
            event = {
                "index": pivot_index,
                "price": pivot["price"],
                "kind": pivot.get("type", pivot.get("kind")),
                "label": pivot.get("label", ""),
                "bos": False,
                "direction": None,
                "confirmation_index": pivot.get("confirmation_index", pivot_index),
                "break_index": None,
            }

            if event["kind"] == "HIGH":
                if last_high is not None and float(pivot["price"]) > float(last_high["price"]):
                    if candles is None:
                        break_index = pivot_index
                    else:
                        previous_confirmation = last_high.get("confirmation_index")
                        if previous_confirmation is None:
                            previous_confirmation = last_high["index"]
                        available_from = int(previous_confirmation) + 1
                        pivot_confirmation = pivot.get("confirmation_index")
                        if pivot_confirmation is None:
                            pivot_confirmation = pivot_index
                        break_index = self._close_break_index(
                            candles, available_from, int(pivot_confirmation) + 1,
                            float(last_high["price"]), "BULLISH",
                        )
                    if break_index is not None:
                        event["bos"] = True
                        event["direction"] = "BULLISH"
                        event["break_index"] = break_index
                last_high = pivot
            elif event["kind"] == "LOW":
                if last_low is not None and float(pivot["price"]) < float(last_low["price"]):
                    if candles is None:
                        break_index = pivot_index
                    else:
                        previous_confirmation = last_low.get("confirmation_index")
                        if previous_confirmation is None:
                            previous_confirmation = last_low["index"]
                        available_from = int(previous_confirmation) + 1
                        pivot_confirmation = pivot.get("confirmation_index")
                        if pivot_confirmation is None:
                            pivot_confirmation = pivot_index
                        break_index = self._close_break_index(
                            candles, available_from, int(pivot_confirmation) + 1,
                            float(last_low["price"]), "BEARISH",
                        )
                    if break_index is not None:
                        event["bos"] = True
                        event["direction"] = "BEARISH"
                        event["break_index"] = break_index
                last_low = pivot

            # Stable identity for the same confirmed pivot/BOS across motors.
            try:
                event_price = float(event["price"])
                price_key = format(event_price, ".12g")
            except (TypeError, ValueError, OverflowError):
                price_key = str(event.get("price"))
            identity_index = (
                event.get("break_index")
                if event.get("break_index") is not None
                else event.get("confirmation_index", pivot_index)
            )
            identity_time = self._event_time_key(candles, identity_index) if candles is not None else f"i{identity_index}"
            event["event_id"] = (
                f"{str(timeframe or 'unknown').lower()}:structure:"
                f"{identity_time}:{str(event.get('kind') or '').upper()}:"
                f"{price_key}:{event.get('break_index') is not None}"
            )
            structure.append(event)

        return structure
