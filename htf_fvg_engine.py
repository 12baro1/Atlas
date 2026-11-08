"""Select fresh, directional higher-timeframe fair-value gaps."""


class HTFFVGEngine:
    def detect(self, h4_fvg, daily_fvg, current_price=None, direction=None):
        direction = str(direction or "NONE").upper()
        expected = "BULLISH" if direction == "LONG" else "BEARISH" if direction == "SHORT" else None
        candidates = []

        for timeframe, gaps, priority in (("4H", h4_fvg or [], 0), ("1D", daily_fvg or [], 1)):
            for gap in gaps:
                if not isinstance(gap, dict) or gap.get("filled"):
                    continue
                kind = str(gap.get("type", "")).upper()
                if expected and kind != expected:
                    continue
                try:
                    low = float(min(gap.get("from"), gap.get("to")))
                    high = float(max(gap.get("from"), gap.get("to")))
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
                        # LONG uses a pullback zone below price; SHORT uses one above.
                        if direction == "LONG" and low > price:
                            continue
                        if direction == "SHORT" and high < price:
                            continue
                        distance = 0.0 if low <= price <= high else (
                            price - high if direction == "LONG" else low - price
                        )

                index = int(gap.get("index", -1) or -1)
                # Prefer the closest actionable POI; timeframe priority breaks ties.
                candidates.append((distance, priority, -index, timeframe, gap, low, high))

        if not candidates:
            return {"valid": False, "timeframe": None, "zone": None, "best": None}

        _, _, _, timeframe, gap, low, high = min(candidates, key=lambda item: item[:3])
        best = {
            "timeframe": timeframe,
            "type": str(gap.get("type", "")).upper(),
            "zone": {"low": low, "high": high},
            "index": gap.get("index"),
            "fill_ratio": gap.get("fill_ratio", 0.0),
            "fvg": gap,
        }
        return {
            "valid": True,
            "timeframe": timeframe,
            "zone": best["zone"],
            "best": best,
        }
