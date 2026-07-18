"""
market_phase_engine.py
Atlas Market Phase Engine v2
Professional market phase detection system for SMC analysis.
"""

class MarketPhaseEngine:
    """
    Detects 8 market phases based on SMC structure, trend, and confluence signals.
    
    Phases:
    - Accumulation: Smart money buying at lows
    - Manipulation: Fake breakout to trap traders
    - Distribution: Smart money selling at highs
    - Expansion: Strong directional move
    - Consolidation: Tight range, preparation
    - Trending: Clear trend establishment
    - Ranging: Price oscillation within zone
    - Reversal: Phase transition indicators
    """

    def detect(
        self,
        structure,
        trend,
        liquidity_sweep,
        fvg,
        orderblocks,
        premium_discount,
        mtf,
        candles=None
    ):
        """Detect current market phase and calculate phase metrics."""
        
        phase_info = self._determine_phase(
            structure=structure,
            trend=trend,
            liquidity_sweep=liquidity_sweep,
            fvg=fvg,
            orderblocks=orderblocks,
            premium_discount=premium_discount,
            mtf=mtf,
            candles=candles
        )
        
        return {
            "phase": phase_info["phase"],
            "phase_confidence": phase_info["confidence"],
            "phase_strength": phase_info["strength"],
            "phase_score": phase_info["score"],
            "trend": trend.get("trend", "RANGE"),
            "trend_strength": trend.get("strength", 0),
            "mtf_valid": mtf.get("valid", False),
            "mtf_alignment": self._calculate_mtf_alignment(mtf),
            "premium": premium_discount.get("premium", False),
            "discount": premium_discount.get("discount", False),
            "structure_active": any(item.get("bos") or item.get("choch") for item in structure),
            "structure_bos": any(item.get("bos") for item in structure),
            "structure_choch": any(item.get("choch") for item in structure),
            "liquidity_active": liquidity_sweep.get("buy_side") or liquidity_sweep.get("sell_side"),
            "fvg_count": len(fvg),
            "orderblock_count": len(orderblocks),
            "phase_indicators": phase_info["indicators"],
        }

    def _determine_phase(
        self,
        structure,
        trend,
        liquidity_sweep,
        fvg,
        orderblocks,
        premium_discount,
        mtf,
        candles=None
    ):
        """Determine market phase using multiple signals."""
        
        # Extract key metrics
        trend_name = trend.get("trend", "RANGE")
        trend_strength = trend.get("strength", 0)
        mtf_valid = mtf.get("valid", False)
        
        # Structure signals
        bos_active = any(item.get("bos") for item in structure)
        choch_active = any(item.get("choch") for item in structure)
        
        # Liquidity signals
        buy_sweep = liquidity_sweep.get("buy_side", False)
        sell_sweep = liquidity_sweep.get("sell_side", False)
        
        # Level signals
        has_fvg = len(fvg) > 0
        has_orderblocks = len(orderblocks) > 0
        premium = premium_discount.get("premium", False)
        discount = premium_discount.get("discount", False)
        
        # Volatility check (optional)
        _volatility = self._calculate_volatility(candles) if candles else "NORMAL"
        
        # Phase determination logic
        phase = "RANGING"  # Default
        confidence = 0
        strength = "WEAK"
        indicators = []
        
        # ACCUMULATION: Smart money buying at lows
        if (discount and has_orderblocks and not (bos_active or choch_active)):
            phase = "Accumulation"
            confidence = 75 if mtf_valid else 60
            strength = "STRONG" if mtf_valid else "NORMAL"
            indicators = ["Discount Zone", "Order Blocks Present", "No Breakout"]
        
        # MANIPULATION: Fake breakout to trap
        elif (bos_active and liquidity_sweep.get("swept_high")) or (choch_active and liquidity_sweep.get("swept_low")):
            phase = "Manipulation"
            confidence = 70
            strength = "STRONG"
            indicators = ["Liquidity Sweep", "Sudden BOS/CHOCH"]
        
        # DISTRIBUTION: Smart money selling at highs
        elif (premium and has_orderblocks and not (bos_active or choch_active)):
            phase = "Distribution"
            confidence = 75 if mtf_valid else 60
            strength = "STRONG" if mtf_valid else "NORMAL"
            indicators = ["Premium Zone", "Order Blocks Present", "No Breakout"]
        
        # EXPANSION: Strong directional move
        elif (trend_name == "BULLISH" or trend_name == "BEARISH") and (bos_active or choch_active) and trend_strength >= 2:
            phase = "Expansion"
            confidence = 85 if mtf_valid else 70
            strength = "ELITE" if trend_strength == 3 else "STRONG"
            indicators = ["Strong Trend", "Market Structure Active", "Momentum High"]
        
        # TRENDING: Clear trend establishment
        elif trend_name in ["BULLISH", "BEARISH"] and trend_strength >= 2:
            phase = "Trending"
            confidence = 80 if mtf_valid else 65
            strength = "STRONG"
            indicators = ["Clear Trend", "Multi-Timeframe Alignment"]
        
        # CONSOLIDATION: Tight range, preparation
        elif trend_name == "RANGE" and has_fvg and has_orderblocks:
            phase = "Consolidation"
            confidence = 70
            strength = "NORMAL"
            indicators = ["Range Bound", "FVG Present", "Order Blocks Present"]
        
        # REVERSAL: Phase transition
        elif (trend_name != "RANGE" and 
              ((buy_sweep and trend_name == "BEARISH") or (sell_sweep and trend_name == "BULLISH"))):
            phase = "Reversal"
            confidence = 65
            strength = "NORMAL"
            indicators = ["Opposite Liquidity Sweep", "Trend Shift Signals"]
        
        # RANGING: Default price oscillation
        else:
            phase = "Ranging"
            confidence = 50 if has_orderblocks or has_fvg else 40
            strength = "WEAK"
            indicators = ["Range Movement", "No Clear Direction"]
        
        # Score calculation
        score = self._calculate_phase_score(
            confidence=confidence,
            phase=phase,
            mtf_valid=mtf_valid,
            structure_active=bos_active or choch_active,
            liquidity_active=buy_sweep or sell_sweep
        )
        
        return {
            "phase": phase,
            "confidence": confidence,
            "strength": strength,
            "score": score,
            "indicators": indicators,
        }

    def _calculate_mtf_alignment(self, mtf):
        """Calculate multi-timeframe alignment score."""
        if not mtf.get("valid"):
            return 0
        
        weekly = mtf.get("weekly", "RANGE")
        daily = mtf.get("daily", "RANGE")
        h4 = mtf.get("h4", "RANGE")
        
        alignment = 0
        if weekly == daily == h4 and weekly != "RANGE":
            alignment = 100
        elif (weekly == daily) or (daily == h4):
            alignment = 75
        elif weekly == h4:
            alignment = 50
        else:
            alignment = 25
        
        return alignment

    def _calculate_phase_score(self, confidence, phase, mtf_valid, structure_active, liquidity_active):
        """Calculate overall phase score."""
        score = confidence
        
        if mtf_valid:
            score += 10
        if structure_active:
            score += 5
        if liquidity_active:
            score += 5
        
        # Phase bonus
        phase_bonus = {
            "Expansion": 10,
            "Trending": 8,
            "Distribution": 8,
            "Accumulation": 8,
            "Consolidation": 5,
            "Reversal": 7,
            "Manipulation": 6,
            "Ranging": 0,
        }
        
        score += phase_bonus.get(phase, 0)
        return min(100, score)

    def _calculate_volatility(self, candles):
        """Calculate volatility level from recent candles."""
        if not candles or len(candles) < 10:
            return "NORMAL"
        
        recent = candles[-10:]
        avg_range = sum((c.high - c.low) for c in recent) / len(recent)
        avg_close = sum(c.close for c in recent) / len(recent)
        
        volatility_percent = (avg_range / avg_close) * 100
        
        if volatility_percent > 2.0:
            return "HIGH"
        elif volatility_percent < 0.5:
            return "LOW"
        else:
            return "NORMAL"
