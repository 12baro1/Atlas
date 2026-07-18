"""
cisd_engine.py
Atlas CISD Engine v1
"""


class CISDEngine:
    """Delivery state değişimini (CISD) çoklu zaman diliminde tespit eder."""

    SUPPORTED_TIMEFRAMES = ("15m", "1h", "4h", "1d")

    def detect_multi(self, timeframe_payload):
        """Tüm zaman dilimlerinde CISD analizi üretir."""
        by_timeframe = {}
        events = []

        for timeframe in self.SUPPORTED_TIMEFRAMES:
            payload = timeframe_payload.get(timeframe)
            if not payload:
                continue

            result = self.detect(
                candles=payload.get("candles") or [],
                structure=payload.get("structure") or [],
                liquidity_sweep=payload.get("liquidity_sweep") or {},
                market_phase=payload.get("market_phase") or {},
                smt=payload.get("smt") or {},
                timeframe=timeframe,
            )
            by_timeframe[timeframe] = result

            if result.get("active"):
                events.append(result)

        best = max(events, key=lambda item: item["confidence"], default=None)

        return {
            "active": best is not None,
            "direction": best["direction"] if best else "NONE",
            "confidence": best["confidence"] if best else 0,
            "best": best,
            "timeframes": by_timeframe,
            "events": events,
        }

    def detect(self, candles, structure, liquidity_sweep, market_phase, smt, timeframe):
        """Tek zaman diliminde CISD tespiti yapar."""
        if len(candles) < 12:
            return self._empty(timeframe)

        current_state = self._delivery_state(candles[-6:])
        previous_state = self._delivery_state(candles[-12:-6])

        if current_state == previous_state:
            return self._empty(timeframe)

        direction = "BULLISH" if current_state == "BUY" else "BEARISH"
        structure_confirmation = self._structure_confirmation(structure, direction)
        impulse_score = self._impulse_strength(candles[-6:])
        sweep_confirmation = self._sweep_confirmation(liquidity_sweep, direction)
        smt_confirmation = bool(smt.get("active") and smt.get("direction") == direction)
        phase_confirmation = self._phase_alignment(market_phase, direction)

        confidence = self._confidence_score(
            timeframe=timeframe,
            impulse_score=impulse_score,
            structure_confirmation=structure_confirmation,
            sweep_confirmation=sweep_confirmation,
            smt_confirmation=smt_confirmation,
            phase_confirmation=phase_confirmation,
            previous_state=previous_state,
            current_state=current_state,
        )

        return {
            "active": confidence >= 55,
            "timeframe": timeframe,
            "direction": direction,
            "from_state": previous_state,
            "to_state": current_state,
            "impulse_score": impulse_score,
            "confidence": confidence,
            "confirmed_by": {
                "structure": structure_confirmation,
                "liquidity_sweep": sweep_confirmation,
                "market_phase": phase_confirmation,
                "smt": smt_confirmation,
            },
        }

    def _delivery_state(self, candles):
        """Mum gövdesi baskınlığına göre delivery state üretir."""
        bullish_pressure = 0.0
        bearish_pressure = 0.0

        for candle in candles:
            body = abs(candle.close - candle.open)
            total_range = max(candle.high - candle.low, 1e-9)
            body_ratio = body / total_range

            if candle.close >= candle.open:
                bullish_pressure += body_ratio
            else:
                bearish_pressure += body_ratio

        if bullish_pressure > bearish_pressure * 1.12:
            return "BUY"
        if bearish_pressure > bullish_pressure * 1.12:
            return "SELL"
        return "NEUTRAL"

    def _impulse_strength(self, candles):
        """Son pencere içindeki displacement gücünü skorlar."""
        ranges = [max(c.high - c.low, 1e-9) for c in candles]
        avg_range = sum(ranges) / len(ranges)

        best = 0
        for candle in candles:
            current_range = candle.high - candle.low
            body = abs(candle.close - candle.open)
            body_ratio = body / max(current_range, 1e-9)

            score = 0
            if current_range >= avg_range * 1.3:
                score += 45
            if body_ratio >= 0.6:
                score += 35
            if current_range >= avg_range * 1.8:
                score += 20

            best = max(best, score)

        return max(0, min(100, best))

    def _structure_confirmation(self, structure, direction):
        if not structure:
            return False

        recent = structure[-5:]
        for item in reversed(recent):
            if item.get("direction") != direction:
                continue
            if item.get("bos") or item.get("choch"):
                return True
        return False

    def _sweep_confirmation(self, liquidity_sweep, direction):
        if direction == "BULLISH":
            return bool(liquidity_sweep.get("sell_side"))
        return bool(liquidity_sweep.get("buy_side"))

    def _phase_alignment(self, market_phase, direction):
        phase = (market_phase or {}).get("phase", "Ranging")

        bullish_friendly = {"Expansion", "Trending", "Accumulation", "Reversal"}
        bearish_friendly = {"Expansion", "Trending", "Distribution", "Reversal"}

        if direction == "BULLISH":
            return phase in bullish_friendly
        return phase in bearish_friendly

    def _confidence_score(
        self,
        timeframe,
        impulse_score,
        structure_confirmation,
        sweep_confirmation,
        smt_confirmation,
        phase_confirmation,
        previous_state,
        current_state,
    ):
        timeframe_bonus = {
            "15m": 0,
            "1h": 5,
            "4h": 9,
            "1d": 13,
        }.get(timeframe, 0)

        score = 30 + timeframe_bonus
        score += int(impulse_score * 0.35)

        if structure_confirmation:
            score += 15
        if sweep_confirmation:
            score += 10
        if smt_confirmation:
            score += 8
        if phase_confirmation:
            score += 8

        if previous_state == "NEUTRAL" or current_state == "NEUTRAL":
            score -= 8

        return max(0, min(100, score))

    def _empty(self, timeframe):
        return {
            "active": False,
            "timeframe": timeframe,
            "direction": "NONE",
            "from_state": "NEUTRAL",
            "to_state": "NEUTRAL",
            "impulse_score": 0,
            "confidence": 0,
            "confirmed_by": {
                "structure": False,
                "liquidity_sweep": False,
                "market_phase": False,
                "smt": False,
            },
        }
