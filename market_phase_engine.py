"""
market_phase_engine.py
Atlas Market Phase Engine
"""


class MarketPhaseEngine:
    """
    Detects the active market phase from SMC analysis components.
    """

    def detect(
        self,
        structure,
        trend,
        liquidity_sweep,
        fvg,
        orderblocks,
        premium_discount,
        mtf
    ):
        scores = {
            "EXPANSION": 0,
            "RETRACEMENT": 0,
            "ACCUMULATION": 0,
            "DISTRIBUTION": 0
        }

        last_event = self._last_structure_event(structure)
        trend_name = self._trend_name(trend)
        mtf_entry = mtf.get("entry") if isinstance(mtf, dict) else None
        mtf_valid = bool(mtf.get("valid")) if isinstance(mtf, dict) else False

        has_bos = bool(last_event and last_event.get("bos"))
        has_choch = bool(last_event and last_event.get("choch"))
        direction = last_event.get("direction") if last_event else None

        active_fvg = self._has_active_fvg(fvg)
        active_orderblock = self._has_active_orderblock(orderblocks)
        buy_sweep = bool(liquidity_sweep.get("buy_side")) if isinstance(liquidity_sweep, dict) else False
        sell_sweep = bool(liquidity_sweep.get("sell_side")) if isinstance(liquidity_sweep, dict) else False
        premium = bool(premium_discount.get("premium")) if isinstance(premium_discount, dict) else False
        discount = bool(premium_discount.get("discount")) if isinstance(premium_discount, dict) else False

        if has_bos:
            scores["EXPANSION"] += 30

        if active_fvg:
            scores["EXPANSION"] += 15
            scores["RETRACEMENT"] += 10

        if active_orderblock:
            scores["EXPANSION"] += 10
            scores["RETRACEMENT"] += 15

        if mtf_valid:
            scores["EXPANSION"] += 15

        if trend_name in ["BULLISH", "BEARISH"]:
            scores["EXPANSION"] += 10
        else:
            scores["ACCUMULATION"] += 10
            scores["DISTRIBUTION"] += 10

        if has_choch:
            scores["RETRACEMENT"] += 25

        if buy_sweep or sell_sweep:
            scores["RETRACEMENT"] += 20
            scores["ACCUMULATION"] += 10
            scores["DISTRIBUTION"] += 10

        if discount:
            scores["ACCUMULATION"] += 25

        if premium:
            scores["DISTRIBUTION"] += 25

        if trend_name == "BULLISH" and direction == "BULLISH":
            scores["EXPANSION"] += 15

        if trend_name == "BEARISH" and direction == "BEARISH":
            scores["EXPANSION"] += 15

        if trend_name == "BULLISH" and sell_sweep:
            scores["ACCUMULATION"] += 15

        if trend_name == "BEARISH" and buy_sweep:
            scores["DISTRIBUTION"] += 15

        if mtf_entry == "LONG" and discount:
            scores["ACCUMULATION"] += 10

        if mtf_entry == "SHORT" and premium:
            scores["DISTRIBUTION"] += 10

        phase = max(scores, key=scores.get)
        confidence = min(100, max(0, scores[phase]))

        return {
            "phase": phase,
            "valid": confidence >= 40,
            "confidence": confidence
        }

    def _last_structure_event(self, structure):
        if not structure:
            return None

        for event in reversed(structure):
            if event.get("bos") or event.get("choch"):
                return event

        return structure[-1]

    def _trend_name(self, trend):
        if isinstance(trend, dict):
            return trend.get("trend", "RANGE")

        return trend or "RANGE"

    def _has_active_fvg(self, fvg):
        return any(not gap.get("filled", False) for gap in fvg or [])

    def _has_active_orderblock(self, orderblocks):
        return any(not block.get("mitigated", False) for block in orderblocks or [])
