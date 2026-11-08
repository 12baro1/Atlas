"""Close-confirmed break-of-structure detection."""


class BOSEngine:
    @staticmethod
    def _value(candle, name):
        if isinstance(candle, dict):
            return float(candle[name])
        return float(getattr(candle, name))

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

    def detect(self, pivots, candles=None):
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
                        available_from = int(last_high.get("confirmation_index", last_high["index"])) + 1
                        break_index = self._close_break_index(
                            candles, available_from, pivot_index + 1,
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
                        available_from = int(last_low.get("confirmation_index", last_low["index"])) + 1
                        break_index = self._close_break_index(
                            candles, available_from, pivot_index + 1,
                            float(last_low["price"]), "BEARISH",
                        )
                    if break_index is not None:
                        event["bos"] = True
                        event["direction"] = "BEARISH"
                        event["break_index"] = break_index
                last_low = pivot

            structure.append(event)

        return structure
