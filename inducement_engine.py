"""
inducement_engine.py
Atlas Inducement Engine
"""


class InducementEngine:
    """Detects SMC inducement liquidity taken before BOS/CHOCH continuation."""

    def __init__(self, min_confidence=65):
        self.min_confidence = min_confidence

    def detect(self, timeframes, trend, liquidity_sweep, eqh_eql, market_phase):
        candidates = []
        for timeframe, payload in (timeframes or {}).items():
            candidate = self._detect_timeframe(
                timeframe=timeframe,
                structure=payload.get("structure", []),
                fvg=payload.get("fvg", []),
                orderblocks=payload.get("orderblocks", []),
                breaker=payload.get("breaker", []),
                trend=trend,
                liquidity_sweep=liquidity_sweep if timeframe == "15m" else None,
                eqh_eql=eqh_eql,
                market_phase=market_phase,
            )
            if candidate["valid"]:
                candidates.append(candidate)

        candidates.sort(key=lambda item: (-item["confidence"], item["timeframe"]))
        best = candidates[0] if candidates else None
        return {
            "valid": best is not None,
            "confidence": best["confidence"] if best else 0,
            "direction": best["direction"] if best else None,
            "price": best["price"] if best else None,
            "timeframe": best["timeframe"] if best else None,
            "reason": best["reason"] if best else "No valid inducement detected",
            "summary": best["summary"] if best else "IDM not confirmed",
            "idms": candidates,
        }

    def _detect_timeframe(self, timeframe, structure, fvg, orderblocks, breaker, trend, liquidity_sweep, eqh_eql, market_phase):
        event = self._last_break_event(structure)
        direction = self._direction(event)
        inducement = self._inducement_swing(structure, event, direction)
        if not event or not direction or not inducement:
            return self._invalid(timeframe)

        score = 35
        reasons = ["BOS/CHOCH öncesi karşı taraf likiditesi bulundu"]
        checks = (
            (20, self._relevant_sweep(direction, liquidity_sweep), "Likidite sweep yön ile uyumlu"),
            (15, self._relevant_equal_liquidity(direction, timeframe, eqh_eql), "EQH/EQL likidite havuzu IDM bölgesini destekliyor"),
            (10, self._relevant_orderblock(direction, orderblocks), "Order block IDM bölgesiyle uyumlu"),
            (10, self._relevant_fvg(direction, fvg), "FVG displacement sonrası boşluk teyidi var"),
            (8, bool(breaker), "Breaker block ek teyit sağlıyor"),
            (10, self._trend_aligned(direction, trend), "Trend IDM yönüyle uyumlu"),
            (8, self._phase_supports(direction, market_phase), "Market phase IDM senaryosunu destekliyor"),
        )
        for points, passed, reason in checks:
            if passed:
                score += points
                reasons.append(reason)

        confidence = min(100, score)
        price = inducement.get("price")
        label = "Bullish" if direction == "BULLISH" else "Bearish"
        return {
            "valid": confidence >= self.min_confidence,
            "confidence": confidence,
            "direction": direction,
            "price": price,
            "timeframe": timeframe,
            "reason": "; ".join(reasons),
            "summary": f"{label} IDM @ {round(price, 4)} on {timeframe} ({confidence}%)",
        }

    def _invalid(self, timeframe):
        return {
            "valid": False,
            "confidence": 0,
            "direction": None,
            "price": None,
            "timeframe": timeframe,
            "reason": "BOS/CHOCH öncesi yeterli inducement yapısı yok",
            "summary": "IDM not confirmed",
        }

    def _last_break_event(self, structure):
        for event in reversed(structure or []):
            if event.get("bos") or event.get("choch"):
                return event
        return None

    def _direction(self, event):
        direction = event.get("direction") if event else None
        return direction if direction in ("BULLISH", "BEARISH") else None

    def _inducement_swing(self, structure, event, direction):
        event_index = event.get("index", 0) if event else 0
        wanted = "LOW" if direction == "BULLISH" else "HIGH"
        candidates = [
            item for item in structure or []
            if (item.get("kind") == wanted or item.get("type") == wanted) and item.get("index", 0) < event_index
        ]
        return candidates[-1] if candidates else None

    def _relevant_sweep(self, direction, liquidity_sweep):
        if not isinstance(liquidity_sweep, dict):
            return False
        return bool(liquidity_sweep.get("sell_side" if direction == "BULLISH" else "buy_side"))

    def _relevant_equal_liquidity(self, direction, timeframe, eqh_eql):
        if not isinstance(eqh_eql, dict):
            return False
        wanted = "EQL" if direction == "BULLISH" else "EQH"
        return any(
            zone.get("type") == wanted and (zone.get("timeframe") == timeframe or timeframe == "15m") and not zone.get("swept")
            for zone in eqh_eql.get("zones", [])
        )

    def _relevant_orderblock(self, direction, orderblocks):
        wanted = "BULLISH" if direction == "BULLISH" else "BEARISH"
        return any(block.get("type") == wanted and not block.get("mitigated", False) for block in orderblocks or [])

    def _relevant_fvg(self, direction, fvg):
        wanted = "BULLISH" if direction == "BULLISH" else "BEARISH"
        return any(gap.get("type") == wanted and not gap.get("filled", False) for gap in fvg or [])

    def _trend_aligned(self, direction, trend):
        return isinstance(trend, dict) and trend.get("trend") == direction

    def _phase_supports(self, direction, market_phase):
        if not isinstance(market_phase, dict):
            return False
        bullish_phases = ("ACCUMULATION", "RETRACEMENT", "EXPANSION")
        bearish_phases = ("DISTRIBUTION", "RETRACEMENT", "EXPANSION")
        return market_phase.get("phase") in (bullish_phases if direction == "BULLISH" else bearish_phases)
