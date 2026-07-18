"""
market_phase_engine.py
Atlas Market Phase Engine
"""


class MarketPhaseEngine:
    """Classifies the current Smart Money Concepts market phase."""

    PHASES = ("EXPANSION", "RETRACEMENT", "ACCUMULATION", "DISTRIBUTION")

    def detect(
        self,
        structure,
        trend,
        liquidity_sweep,
        fvg,
        orderblocks,
        premium_discount,
        mtf,
    ):
        scores = {phase: 0 for phase in self.PHASES}
        reasons = {phase: [] for phase in self.PHASES}

        last_event = self._last_structure_event(structure)
        trend_name = self._trend_name(trend)
        direction = last_event.get("direction") if last_event else None
        has_bos = bool(last_event and last_event.get("bos"))
        has_choch = bool(last_event and last_event.get("choch"))
        has_fvg = self._has_open_item(fvg, "filled")
        has_ob = self._has_open_item(orderblocks, "mitigated")
        buy_sweep = self._flag(liquidity_sweep, "buy_side")
        sell_sweep = self._flag(liquidity_sweep, "sell_side")
        premium = self._flag(premium_discount, "premium")
        discount = self._flag(premium_discount, "discount")
        mtf_valid = self._flag(mtf, "valid")
        mtf_entry = mtf.get("entry") if isinstance(mtf, dict) else None

        self._add(scores, reasons, "EXPANSION", 30 if has_bos else 0, "BOS displacement")
        self._add(scores, reasons, "EXPANSION", 15 if has_fvg else 0, "active FVG")
        self._add(scores, reasons, "EXPANSION", 10 if has_ob else 0, "active order block")
        self._add(scores, reasons, "EXPANSION", 15 if mtf_valid else 0, "MTF alignment")
        self._add(scores, reasons, "EXPANSION", 10 if trend_name in ("BULLISH", "BEARISH") else 0, "directional trend")
        self._add(scores, reasons, "EXPANSION", 15 if direction == trend_name and direction in ("BULLISH", "BEARISH") else 0, "structure follows trend")

        self._add(scores, reasons, "RETRACEMENT", 25 if has_choch else 0, "CHOCH reaction")
        self._add(scores, reasons, "RETRACEMENT", 20 if buy_sweep or sell_sweep else 0, "liquidity sweep")
        self._add(scores, reasons, "RETRACEMENT", 10 if has_fvg else 0, "FVG pullback target")
        self._add(scores, reasons, "RETRACEMENT", 15 if has_ob else 0, "order block retest")

        range_bonus = 10 if trend_name == "RANGE" else 0
        self._add(scores, reasons, "ACCUMULATION", range_bonus, "range trend")
        self._add(scores, reasons, "DISTRIBUTION", range_bonus, "range trend")
        self._add(scores, reasons, "ACCUMULATION", 25 if discount else 0, "discount pricing")
        self._add(scores, reasons, "DISTRIBUTION", 25 if premium else 0, "premium pricing")
        self._add(scores, reasons, "ACCUMULATION", 15 if trend_name == "BULLISH" and sell_sweep else 0, "sell-side sweep in bullish context")
        self._add(scores, reasons, "DISTRIBUTION", 15 if trend_name == "BEARISH" and buy_sweep else 0, "buy-side sweep in bearish context")
        self._add(scores, reasons, "ACCUMULATION", 10 if mtf_entry == "LONG" and discount else 0, "discount MTF long context")
        self._add(scores, reasons, "DISTRIBUTION", 10 if mtf_entry == "SHORT" and premium else 0, "premium MTF short context")

        phase = max(scores, key=scores.get)
        confidence = max(0, min(100, scores[phase]))
        return {
            "phase": phase,
            "valid": confidence >= 40,
            "confidence": confidence,
        }

    def _add(self, scores, reasons, phase, points, reason):
        if points <= 0:
            return
        scores[phase] += points
        reasons[phase].append(reason)

    def _last_structure_event(self, structure):
        for event in reversed(structure or []):
            if event.get("bos") or event.get("choch"):
                return event
        return structure[-1] if structure else None

    def _trend_name(self, trend):
        return trend.get("trend", "RANGE") if isinstance(trend, dict) else (trend or "RANGE")

    def _flag(self, payload, key):
        return bool(payload.get(key)) if isinstance(payload, dict) else False

    def _has_open_item(self, items, closed_key):
        return any(not item.get(closed_key, False) for item in items or [])
