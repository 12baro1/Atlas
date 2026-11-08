"""Select fresh, directional and still-actionable higher-timeframe order blocks."""


class HTFOrderBlockEngine:
    def detect(self, current_price, daily_orderblocks, h4_orderblocks, direction=None):
        direction = str(direction or "NONE").upper()
        expected = "BULLISH" if direction == "LONG" else "BEARISH" if direction == "SHORT" else None
        candidates = []

        for timeframe, blocks, priority in (("H4", h4_orderblocks or [], 0), ("DAILY", daily_orderblocks or [], 1)):
            for block in blocks:
                if not isinstance(block, dict) or block.get("mitigated"):
                    continue
                kind = str(block.get("type", "")).upper()
                if expected and kind != expected:
                    continue
                try:
                    low = float(min(block.get("high"), block.get("low")))
                    high = float(max(block.get("high"), block.get("low")))
                except (TypeError, ValueError, OverflowError):
                    continue
                if not (0 < low < high):
                    continue

                distance = 0.0
                if current_price is not None and direction in {"LONG", "SHORT"}:
                    try:
                        price = float(current_price)
                    except (TypeError, ValueError, OverflowError):
                        price = None
                    if price is not None:
                        if direction == "LONG" and low > price:
                            continue
                        if direction == "SHORT" and high < price:
                            continue
                        distance = 0.0 if low <= price <= high else (
                            price - high if direction == "LONG" else low - price
                        )

                strength = float(block.get("strength", 0) or 0)
                candidates.append((distance, -strength, priority, timeframe, block, low, high))

        if not candidates:
            return {"valid": False, "timeframe": None, "block": None, "zone": None, "best": None}

        _, _, _, timeframe, block, low, high = min(candidates, key=lambda item: item[:3])
        best = {
            "timeframe": timeframe,
            "type": str(block.get("type", "")).upper(),
            "zone": {"low": low, "high": high},
            "strength": block.get("strength", 0),
            "index": block.get("index"),
            "block": block,
        }
        return {
            "valid": True,
            "timeframe": timeframe,
            "block": block,
            "zone": best["zone"],
            "best": best,
        }
