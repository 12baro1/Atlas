"""
market_phase_engine.py
Atlas Market Phase Engine
"""

class MarketPhaseEngine:
    """Detects market phases based on SMC structure and confluence signals."""

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

        phase = self._determine_phase(
            structure=structure,
            trend=trend,
            liquidity_sweep=liquidity_sweep,
            fvg=fvg,
            orderblocks=orderblocks,
            premium_discount=premium_discount,
            mtf=mtf
        )

        return {
            "phase": phase,
            "trend": trend.get("trend", "RANGE"),
            "mtf_valid": mtf.get("valid", False),
            "premium": premium_discount.get("premium", False),
            "discount": premium_discount.get("discount", False),
            "structure_bos": any(item.get("bos") for item in structure),
            "structure_choch": any(item.get("choch") for item in structure),
            "has_fvg": len(fvg) > 0,
            "has_orderblocks": len(orderblocks) > 0,
            "liquidity_sweep": liquidity_sweep,
        }

    def _determine_phase(
        self,
        structure,
        trend,
        liquidity_sweep,
        fvg,
        orderblocks,
        premium_discount,
        mtf
    ):

        trend_name = trend.get("trend", "RANGE")
        mtf_valid = mtf.get("valid", False)
        breakout = liquidity_sweep.get("buy_side") or liquidity_sweep.get("sell_side")
        has_fvg = len(fvg) > 0
        has_orderblocks = len(orderblocks) > 0
        premium = premium_discount.get("premium", False)
        discount = premium_discount.get("discount", False)
        structure_bos = any(item.get("bos") for item in structure)
        structure_choch = any(item.get("choch") for item in structure)

        if trend_name == "BULLISH":
            if breakout and (structure_choch or structure_bos):
                return "Expansion"
            if has_fvg or has_orderblocks:
                return "Retracement"
            if discount:
                return "Accumulation"
            return "Expansion"

        if trend_name == "BEARISH":
            if breakout and (structure_choch or structure_bos):
                return "Expansion"
            if has_fvg or has_orderblocks:
                return "Retracement"
            if premium:
                return "Distribution"
            return "Expansion"

        # Range / neutral behavior
        if premium:
            return "Distribution"
        if discount:
            return "Accumulation"
        if has_orderblocks or has_fvg:
            return "Accumulation"

        if mtf_valid:
            return "Accumulation"

        return "Distribution"
