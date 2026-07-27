"""
plugins/fvg/engine.py
FVG Plugin Engine for Atlas
"""
from core.plugin import Plugin
from .detector import FVGDetector, FVGZone


class FVGEngine(Plugin):
    """
    FVG Plugin Engine
    
    Integrates FVG detection into Atlas plugin system
    """
    name = "FVG"
    
    def __init__(self):
        super().__init__()
        self.detector = FVGDetector()
        
    def run(self, state):
        """
        Run FVG analysis on current market state
        
        Args:
            state: MarketState object with candles
            
        Returns:
            Updated state with FVG data
        """
        if not hasattr(state, 'candles') or not state.candles:
            return state
            
        # Detect FVG zones
        fvg_zones = self.detector.detect(state.candles)
        
        # Get unmitigated zones
        unmitigated = self.detector.get_unmitigated(fvg_zones)
        
        # Get nearest zones for entry planning
        current_price = state.candles[-1].close
        
        nearest_bullish = self.detector.get_nearest(
            current_price=current_price,
            kind="BULLISH",
            zones=fvg_zones
        )
        
        nearest_bearish = self.detector.get_nearest(
            current_price=current_price,
            kind="BEARISH",
            zones=fvg_zones
        )
        
        # Calculate confluence at current price
        confluence_score = self.detector.calculate_confluence(
            price=current_price,
            zones=fvg_zones
        )
        
        # Detect inversion FVGs
        inversions = self.detector.detect_inversion(fvg_zones, state.candles)
        
        # Update state with FVG data
        state.fvg_zones = fvg_zones
        state.fvg_unmitigated = unmitigated
        state.fvg_nearest_bullish = nearest_bullish
        state.fvg_nearest_bearish = nearest_bearish
        state.fvg_confluence = confluence_score
        state.fvg_inversions = inversions
        
        # Add to notes if strong FVG confluence
        if confluence_score >= 50:
            state.notes.append(f"FVG confluence: {confluence_score:.1f}")
            
        # Boost confidence if near strong unmitigated FVG
        if nearest_bullish and nearest_bullish.strength >= 70:
            state.confidence += 15
            state.notes.append("Near strong bullish FVG")
            
        if nearest_bearish and nearest_bearish.strength >= 70:
            state.confidence += 15
            state.notes.append("Near strong bearish FVG")
            
        return state
