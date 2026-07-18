"""
inducement_engine.py
Atlas Inducement Engine
"""


class InducementEngine:
    """
    Detects SMC inducement (IDM) setups before BOS / CHOCH moves.
    """

    def __init__(self, min_confidence=65):
        self.min_confidence = min_confidence

    def detect(
        self,
        timeframes,
        trend,
        liquidity_sweep,
        eqh_eql,
        market_phase
    ):
        idms = []

        for timeframe, payload in timeframes.items():
            candidate = self._detect_timeframe(
                timeframe=timeframe,
                structure=payload.get("structure", []),
                candles=payload.get("candles", []),
                fvg=payload.get("fvg", []),
                orderblocks=payload.get("orderblocks", []),
                breaker=payload.get("breaker", []),
                trend=trend,
                liquidity_sweep=liquidity_sweep if timeframe == "15m" else None,
                eqh_eql=eqh_eql,
                market_phase=market_phase
            )

            if candidate["valid"]:
                idms.append(candidate)

        idms.sort(key=lambda item: (-item["confidence"], item["timeframe"]))
        best = idms[0] if idms else None

        return {
            "valid": best is not None,
            "confidence": best["confidence"] if best else 0,
            "direction": best["direction"] if best else None,
            "price": best["price"] if best else None,
            "timeframe": best["timeframe"] if best else None,
            "reason": best["reason"] if best else "No valid inducement detected",
            "summary": best["summary"] if best else "IDM not confirmed",
            "idms": idms
        }

    def _detect_timeframe(
        self,
        timeframe,
        structure,
        candles,
        fvg,
        orderblocks,
        breaker,
        trend,
        liquidity_sweep,
        eqh_eql,
        market_phase
    ):
        event = self._last_break_event(structure)
        direction = self._direction(event)
        inducement_swing = self._inducement_swing(structure, event, direction)

        if not event or not direction or not inducement_swing:
            return self._invalid(timeframe)

        reasons = []
        confidence = 35

        reasons.append("BOS/CHOCH öncesi karşı taraf likiditesi bulundu")

        if self._relevant_sweep(direction, liquidity_sweep):
            confidence += 20
            reasons.append("Likidite sweep yön ile uyumlu")

        if self._relevant_equal_liquidity(direction, timeframe, eqh_eql):
            confidence += 15
            reasons.append("EQH/EQL likidite havuzu inducement bölgesini destekliyor")

        if self._relevant_orderblock(direction, orderblocks):
            confidence += 10
            reasons.append("Order block IDM bölgesiyle uyumlu")

        if self._relevant_fvg(direction, fvg):
            confidence += 10
            reasons.append("FVG displacement sonrası boşluk teyidi var")

        if breaker:
            confidence += 8
            reasons.append("Breaker block ek teyit sağlıyor")

        if self._trend_aligned(direction, trend):
            confidence += 10
            reasons.append("Trend IDM yönüyle uyumlu")

        if self._phase_supports(direction, market_phase):
            confidence += 8
            reasons.append("Market phase IDM senaryosunu destekliyor")

        confidence = min(100, confidence)
        valid = confidence >= self.min_confidence
        price = inducement_swing.get("price")
        side = "Bullish" if direction == "BULLISH" else "Bearish"

        return {
            "valid": valid,
            "confidence": confidence,
            "direction": direction,
            "price": price,
            "timeframe": timeframe,
            "reason": "; ".join(reasons),
            "summary": f"{side} IDM @ {round(price, 4)} on {timeframe} ({confidence}%)"
        }

    def _invalid(self, timeframe):
        return {
            "valid": False,
            "confidence": 0,
            "direction": None,
            "price": None,
            "timeframe": timeframe,
            "reason": "BOS/CHOCH öncesi yeterli inducement yapısı yok",
            "summary": "IDM not confirmed"
        }

    def _last_break_event(self, structure):
        for event in reversed(structure or []):
            if event.get("bos") or event.get("choch"):
                return event

        return None

    def _direction(self, event):
        if not event:
            return None

        direction = event.get("direction")

        if direction in ["BULLISH", "BEARISH"]:
            return direction

        return None

    def _inducement_swing(self, structure, event, direction):
        if not event:
            return None

        event_index = event.get("index", 0)
        wanted_type = "LOW" if direction == "BULLISH" else "HIGH"
        candidates = [
            item
            for item in structure or []
            if (item.get("kind") == wanted_type or item.get("type") == wanted_type)
            and item.get("index", 0) < event_index
        ]

        if not candidates:
            return None

        return candidates[-1]

    def _relevant_sweep(self, direction, liquidity_sweep):
        if not isinstance(liquidity_sweep, dict):
            return False

        if direction == "BULLISH":
            return bool(liquidity_sweep.get("sell_side"))

        return bool(liquidity_sweep.get("buy_side"))

    def _relevant_equal_liquidity(self, direction, timeframe, eqh_eql):
        if not isinstance(eqh_eql, dict):
            return False

        wanted_type = "EQL" if direction == "BULLISH" else "EQH"

        for zone in eqh_eql.get("zones", []):
            if zone.get("type") != wanted_type:
                continue

            if zone.get("timeframe") == timeframe or timeframe == "15m":
                return True

        return False

    def _relevant_orderblock(self, direction, orderblocks):
        wanted_type = "BULLISH" if direction == "BULLISH" else "BEARISH"

        return any(
            block.get("type") == wanted_type and not block.get("mitigated", False)
            for block in orderblocks or []
        )

    def _relevant_fvg(self, direction, fvg):
        wanted_type = "BULLISH" if direction == "BULLISH" else "BEARISH"

        return any(
            gap.get("type") == wanted_type and not gap.get("filled", False)
            for gap in fvg or []
        )

    def _trend_aligned(self, direction, trend):
        if not isinstance(trend, dict):
            return False

        return trend.get("trend") == direction

    def _phase_supports(self, direction, market_phase):
        if not isinstance(market_phase, dict):
            return False

        phase = market_phase.get("phase")

        if direction == "BULLISH":
            return phase in ["ACCUMULATION", "RETRACEMENT", "EXPANSION"]

        return phase in ["DISTRIBUTION", "RETRACEMENT", "EXPANSION"]
