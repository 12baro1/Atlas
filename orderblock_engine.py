"""
orderblock_engine.py
Atlas Order Block Engine v4
"""

class OrderBlockEngine:

    @staticmethod
    def _event_id(candles, index, direction, high, low):
        try:
            candle = candles[int(index)]
            timestamp = getattr(candle, "time", None)
            if timestamp is None and isinstance(candle, dict):
                timestamp = candle.get("time", candle.get("timestamp"))
            if timestamp is None:
                return None
            return (
                f"orderblock:{str(direction).upper()}:{int(timestamp)}:"
                f"{format(float(high), '.12g')}:{format(float(low), '.12g')}"
            )
        except (IndexError, KeyError, TypeError, ValueError, OverflowError):
            return None

    def detect(self, candles, structure):

        blocks = []

        for item in structure:

            if not item.get("bos"):
                continue

            idx = int(item.get("index", 0))
            break_index = item.get("break_index")
            try:
                break_index = int(break_index) if break_index is not None else idx
            except (TypeError, ValueError, OverflowError):
                break_index = idx
            if break_index <= 0 or break_index > len(candles):
                continue

            # The OB is the last opposing candle before the confirmed close
            # through structure, not blindly the candle before the swing pivot.
            prev = None
            ob_index = None
            search_start = max(0, break_index - 12)
            for candidate_index in range(break_index - 1, search_start - 1, -1):
                candidate = candles[candidate_index]
                if item.get("direction") == "BULLISH" and candidate.close < candidate.open:
                    prev, ob_index = candidate, candidate_index
                    break
                if item.get("direction") == "BEARISH" and candidate.close > candidate.open:
                    prev, ob_index = candidate, candidate_index
                    break
            if prev is None:
                continue

            # -------------------------
            # Bullish Order Block
            # -------------------------

            if item["direction"] == "BULLISH":

                if prev.close < prev.open:

                    strength = 0

                    body = abs(prev.close - prev.open)
                    wick = prev.high - prev.low

                    if wick > 0:

                        body_ratio = body / wick

                        if body_ratio >= 0.70:
                            strength += 40

                        elif body_ratio >= 0.50:
                            strength += 30

                        else:
                            strength += 20

                    strength += 20

                    if item["label"] == "HH":
                        strength += 20

                    if item.get("choch"):
                        strength += 20

                    blocks.append({
                        "type": "BULLISH",
                        "event_id": self._event_id(candles, ob_index, "BULLISH", prev.high, prev.low),
                        "index": ob_index,
                        "break_index": break_index,
                        "high": prev.high,
                        "low": prev.low,
                        "strength": strength,
                        "mitigated": False
                    })

            # -------------------------
            # Bearish Order Block
            # -------------------------

            elif item["direction"] == "BEARISH":

                if prev.close > prev.open:

                    strength = 0

                    body = abs(prev.close - prev.open)
                    wick = prev.high - prev.low

                    if wick > 0:

                        body_ratio = body / wick

                        if body_ratio >= 0.70:
                            strength += 40

                        elif body_ratio >= 0.50:
                            strength += 30

                        else:
                            strength += 20

                    strength += 20

                    if item["label"] == "LL":
                        strength += 20

                    if item.get("choch"):
                        strength += 20

                    blocks.append({
                        "type": "BEARISH",
                        "event_id": self._event_id(candles, ob_index, "BEARISH", prev.high, prev.low),
                        "index": ob_index,
                        "break_index": break_index,
                        "high": prev.high,
                        "low": prev.low,
                        "strength": strength,
                        "mitigated": False
                    })

        return blocks
