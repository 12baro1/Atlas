"""
plugins/fvg/detector.py
Professional Fair Value Gap Detector
SMC Concepts: Imbalance, FVG, Inversion FVG
"""
from dataclasses import dataclass, field
from typing import List, Optional
from core.candle import Candle


@dataclass
class FVGZone:
    """Fair Value Gap Zone"""
    kind: str = ""  # "BULLISH" or "BEARISH"
    start_index: int = 0
    end_index: int = 0
    top: float = 0.0
    bottom: float = 0.0
    midpoint: float = 0.0
    size: float = 0.0
    strength: float = 0.0
    mitigated: bool = False
    mitigation_index: Optional[int] = None
    mitigation_price: Optional[float] = None
    tested_count: int = 0
    is_inversion: bool = False
    parent_ob_index: Optional[int] = None
    timeframes: List[str] = field(default_factory=list)
    
    def to_dict(self):
        return {
            "kind": self.kind,
            "start_index": self.start_index,
            "end_index": self.end_index,
            "top": self.top,
            "bottom": self.bottom,
            "midpoint": self.midpoint,
            "size": self.size,
            "strength": self.strength,
            "mitigated": self.mitigated,
            "mitigation_index": self.mitigation_index,
            "mitigation_price": self.mitigation_price,
            "tested_count": self.tested_count,
            "is_inversion": self.is_inversion,
            "parent_ob_index": self.parent_ob_index,
            "timeframes": self.timeframes
        }


class FVGDetector:
    """
    Professional Fair Value Gap Detector
    
    Detects:
    - Standard FVG (3-candle imbalance)
    - Inversion FVG (failed FVG that flips)
    - Multi-timeframe FVG confluence
    - FVG mitigation status
    """
    
    def __init__(self, min_size_threshold: float = 0.0001):
        self.min_size_threshold = min_size_threshold
        self.zones: List[FVGZone] = []
        
    def detect(
        self,
        candles: List[Candle],
        fvg_zones: Optional[List[FVGZone]] = None
    ) -> List[FVGZone]:
        """
        Detect all FVG zones in the candle series
        
        Args:
            candles: List of Candle objects
            fvg_zones: Optional existing zones to update
            
        Returns:
            List of FVGZone objects
        """
        if len(candles) < 3:
            return []
            
        self.zones = []
        
        for i in range(2, len(candles)):
            left = candles[i - 2]
            mid = candles[i - 1]
            right = candles[i]
            
            # Bullish FVG: left.high < right.low
            if left.high < right.low:
                zone = self._create_bullish_fvg(i, left, mid, right, candles)
                if zone and zone.size >= self.min_size_threshold:
                    self.zones.append(zone)
                    
            # Bearish FVG: left.low > right.high
            elif left.low > right.high:
                zone = self._create_bearish_fvg(i, left, mid, right, candles)
                if zone and zone.size >= self.min_size_threshold:
                    self.zones.append(zone)
        
        # Update mitigation status for existing zones
        if fvg_zones:
            self._update_mitigation(fvg_zones, candles)
            
        return self.zones
        
    def _create_bullish_fvg(
        self,
        index: int,
        left: Candle,
        mid: Candle,
        right: Candle,
        candles: List[Candle]
    ) -> Optional[FVGZone]:
        """Create bullish FVG zone"""
        top = right.low
        bottom = left.high
        size = top - bottom
        
        if size <= 0:
            return None
            
        # Calculate strength based on multiple factors
        strength = self._calculate_strength(
            mid=mid,
            right=right,
            size=size,
            is_bullish=True
        )
        
        zone = FVGZone(
            kind="BULLISH",
            start_index=index - 2,
            end_index=index,
            top=top,
            bottom=bottom,
            midpoint=(top + bottom) / 2,
            size=size,
            strength=strength,
            mitigated=False,
            tested_count=0
        )
        
        # Check immediate mitigation
        self._check_mitigation(zone, candles, index + 1)
        
        return zone
        
    def _create_bearish_fvg(
        self,
        index: int,
        left: Candle,
        mid: Candle,
        right: Candle,
        candles: List[Candle]
    ) -> Optional[FVGZone]:
        """Create bearish FVG zone"""
        top = left.low
        bottom = right.high
        size = top - bottom
        
        if size <= 0:
            return None
            
        strength = self._calculate_strength(
            mid=mid,
            right=right,
            size=size,
            is_bullish=False
        )
        
        zone = FVGZone(
            kind="BEARISH",
            start_index=index - 2,
            end_index=index,
            top=top,
            bottom=bottom,
            midpoint=(top + bottom) / 2,
            size=size,
            strength=strength,
            mitigated=False,
            tested_count=0
        )
        
        self._check_mitigation(zone, candles, index + 1)
        
        return zone
        
    def _calculate_strength(
        self,
        mid: Candle,
        right: Candle,
        size: float,
        is_bullish: bool
    ) -> float:
        """
        Calculate FVG strength (0-100)
        
        Factors:
        - Size relative to ATR/candle range
        - Mid candle direction and body size
        - Right candle confirmation
        - Displacement magnitude
        """
        strength = 0.0
        
        # Base strength from size (max 40 points)
        # Assuming average candle range, normalize size
        avg_range = (mid.range + right.range) / 2
        if avg_range > 0:
            size_ratio = size / avg_range
            strength += min(size_ratio * 20, 40)
            
        # Mid candle direction (max 20 points)
        if is_bullish and mid.close > mid.open:
            strength += 15
            # Body ratio bonus
            if mid.body > 0:
                body_ratio = mid.body / mid.range if mid.range > 0 else 0
                strength += min(body_ratio * 10, 5)
        elif not is_bullish and mid.close < mid.open:
            strength += 15
            if mid.body > 0:
                body_ratio = mid.body / mid.range if mid.range > 0 else 0
                strength += min(body_ratio * 10, 5)
                
        # Right candle confirmation (max 20 points)
        if is_bullish and right.close > right.open:
            strength += 10
            if right.close > mid.high:
                strength += 10  # Strong displacement
        elif not is_bullish and right.close < right.open:
            strength += 10
            if right.close < mid.low:
                strength += 10
                
        # Wick analysis (max 20 points)
        if is_bullish:
            if right.lower_wick < right.body * 0.5:
                strength += 10  # Clean break
            if mid.upper_wick < mid.body:
                strength += 10  # Strong momentum
        else:
            if right.upper_wick < right.body * 0.5:
                strength += 10
            if mid.lower_wick < mid.body:
                strength += 10
                
        return min(strength, 100.0)
        
    def _check_mitigation(
        self,
        zone: FVGZone,
        candles: List[Candle],
        start_index: int
    ):
        """Check if FVG has been mitigated by subsequent price action"""
        if start_index >= len(candles):
            return
            
        for i in range(start_index, len(candles)):
            candle = candles[i]
            
            # Check if candle intersects FVG zone
            if zone.kind == "BULLISH":
                if candle.low <= zone.top and candle.high >= zone.bottom:
                    zone.mitigated = True
                    zone.mitigation_index = i
                    zone.mitigation_price = candle.close
                    break
            else:  # BEARISH
                if candle.high >= zone.bottom and candle.low <= zone.top:
                    zone.mitigated = True
                    zone.mitigation_index = i
                    zone.mitigation_price = candle.close
                    break
                    
    def _update_mitigation(
        self,
        zones: List[FVGZone],
        candles: List[Candle]
    ):
        """Update mitigation status for existing zones"""
        for zone in zones:
            if zone.mitigated:
                continue
                
            start_check = zone.end_index + 1
            if start_check >= len(candles):
                continue
                
            self._check_mitigation(zone, candles, start_check)
            
    def get_unmitigated(
        self,
        zones: Optional[List[FVGZone]] = None
    ) -> List[FVGZone]:
        """Get all unmitigated FVG zones"""
        target = zones if zones else self.zones
        return [z for z in target if not z.mitigated]
        
    def get_by_kind(
        self,
        kind: str,
        zones: Optional[List[FVGZone]] = None
    ) -> List[FVGZone]:
        """Get FVG zones by type (BULLISH/BEARISH)"""
        target = zones if zones else self.zones
        return [z for z in target if z.kind == kind]
        
    def get_nearest(
        self,
        current_price: float,
        kind: str,
        zones: Optional[List[FVGZone]] = None
    ) -> Optional[FVGZone]:
        """
        Get nearest unmitigated FVG zone of specified kind
        
        For BULLISH: nearest below current price
        For BEARISH: nearest above current price
        """
        target = zones if zones else self.zones
        unmitigated = [z for z in target if z.kind == kind and not z.mitigated]
        
        if not unmitigated:
            return None
            
        if kind == "BULLISH":
            # Find highest FVG below current price
            valid = [z for z in unmitigated if z.top < current_price]
            if not valid:
                return None
            return max(valid, key=lambda z: z.top)
        else:
            # Find lowest FVG above current price
            valid = [z for z in unmitigated if z.bottom > current_price]
            if not valid:
                return None
            return min(valid, key=lambda z: z.bottom)
            
    def detect_inversion(
        self,
        zones: List[FVGZone],
        candles: List[Candle]
    ) -> List[FVGZone]:
        """
        Detect inversion FVGs
        
        An inversion FVG occurs when:
        - A bullish FVG fails (price breaks below it) and becomes resistance
        - A bearish FVG fails (price breaks above it) and becomes support
        """
        inversions = []
        
        for zone in zones:
            if not zone.mitigated:
                continue
                
            # Check for inversion after mitigation
            mitigation_idx = zone.mitigation_index
            if mitigation_idx is None or mitigation_idx + 1 >= len(candles):
                continue
                
            # Look for price action after mitigation
            if zone.kind == "BULLISH":
                # Check if price broke below and now uses FVG as resistance
                post_mitigation = candles[mitigation_idx:]
                for i, candle in enumerate(post_mitigation):
                    if candle.high >= zone.top and candle.low <= zone.bottom:
                        # Price rejected from FVG zone
                        zone.is_inversion = True
                        zone.tested_count += 1
                        break
                        
            else:  # BEARISH
                post_mitigation = candles[mitigation_idx:]
                for i, candle in enumerate(post_mitigation):
                    if candle.low <= zone.bottom and candle.high >= zone.top:
                        zone.is_inversion = True
                        zone.tested_count += 1
                        break
                        
            if zone.is_inversion:
                inversions.append(zone)
                
        return inversions
        
    def calculate_confluence(
        self,
        price: float,
        zones: Optional[List[FVGZone]] = None,
        tolerance: float = 0.001
    ) -> float:
        """
        Calculate FVG confluence score at a specific price level
        
        Returns score 0-100 based on how many FVG zones converge at this price
        """
        target = zones if zones else self.zones
        score = 0.0
        
        for zone in target:
            if zone.mitigated and not zone.is_inversion:
                continue
                
            # Check if price is within or near FVG zone
            distance = 0.0
            if price >= zone.bottom and price <= zone.top:
                # Price inside FVG
                distance = 0.0
                score += 25
            elif zone.kind == "BULLISH":
                distance = zone.bottom - price
            else:
                distance = price - zone.top
                
            if 0 < distance <= zone.top * tolerance:
                # Price near FVG
                proximity_score = max(0, 15 * (1 - distance / (zone.top * tolerance)))
                score += proximity_score
                
        return min(score, 100.0)
