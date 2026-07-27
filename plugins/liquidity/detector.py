"""
plugins/liquidity/detector.py
Professional Liquidity Detector
SMC Concepts: BSL, SSL, EQH, EQL, Liquidity Grabs, Sweep Detection
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple
from core.candle import Candle


@dataclass
class LiquidityPool:
    """Liquidity Pool representing a cluster of stop losses"""
    kind: str = ""  # "BUY_SIDE" or "SELL_SIDE"
    price: float = 0.0
    touches: int = 0
    strength: float = 0.0
    liquidity_type: str = "SWING"  # "SWING", "INTERNAL", "EQUAL"
    eq_type: Optional[str] = None  # "EQH", "EQL", or None
    swept: bool = False
    sweep_index: Optional[int] = None
    sweep_price: Optional[float] = None
    sweep_kind: Optional[str] = None  # "WICK", "CLOSE", "FALSE_BREAK"
    indices: List[int] = field(default_factory=list)
    timeframes: List[str] = field(default_factory=list)
    
    def to_dict(self):
        return {
            "kind": self.kind,
            "price": self.price,
            "touches": self.touches,
            "strength": self.strength,
            "liquidity_type": self.liquidity_type,
            "eq_type": self.eq_type,
            "swept": self.swept,
            "sweep_index": self.sweep_index,
            "sweep_price": self.sweep_price,
            "sweep_kind": self.sweep_kind,
            "indices": self.indices,
            "timeframes": self.timeframes
        }


@dataclass
class LiquiditySweep:
    """Liquidity Sweep Event"""
    kind: str = ""  # "BULLISH" (swept lows) or "BEARISH" (swept highs)
    pool: Optional[LiquidityPool] = None
    sweep_index: int = 0
    sweep_price: float = 0.0
    rejection_index: int = 0
    rejection_price: float = 0.0
    sweep_size: float = 0.0
    rejection_strength: float = 0.0
    is_false_break: bool = False
    follow_through: bool = False
    
    def to_dict(self):
        return {
            "kind": self.kind,
            "pool_price": self.pool.price if self.pool else None,
            "sweep_index": self.sweep_index,
            "sweep_price": self.sweep_price,
            "rejection_index": self.rejection_index,
            "rejection_price": self.rejection_price,
            "sweep_size": self.sweep_size,
            "rejection_strength": self.rejection_strength,
            "is_false_break": self.is_false_break,
            "follow_through": self.follow_through
        }


class LiquidityDetector:
    """
    Professional Liquidity Detector
    
    Detects:
    - Buy Side Liquidity (BSL) - above swing highs
    - Sell Side Liquidity (SSL) - below swing lows
    - Equal Highs (EQH) and Equal Lows (EQL)
    - Liquidity sweeps and grabs
    - False breaks and rejections
    """
    
    def __init__(
        self,
        tolerance: float = 0.001,
        min_touches: int = 2,
        swing_lookback: int = 10
    ):
        self.tolerance = tolerance
        self.min_touches = min_touches
        self.swing_lookback = swing_lookback
        self.pools: List[LiquidityPool] = []
        self.sweeps: List[LiquiditySweep] = []
        
    def detect_pools(
        self,
        candles: List[Candle],
        swing_highs: List[Tuple[int, float]],
        swing_lows: List[Tuple[int, float]]
    ) -> List[LiquidityPool]:
        """
        Detect liquidity pools from swing points
        
        Args:
            candles: List of Candle objects
            swing_highs: List of (index, price) tuples for swing highs
            swing_lows: List of (index, price) tuples for swing lows
            
        Returns:
            List of LiquidityPool objects
        """
        self.pools = []
        
        # Detect Buy Side Liquidity (above highs)
        bsl_pools = self._cluster_liquidity(
            points=swing_highs,
            kind="BUY_SIDE",
            candles=candles
        )
        
        # Detect Sell Side Liquidity (below lows)
        ssl_pools = self._cluster_liquidity(
            points=swing_lows,
            kind="SELL_SIDE",
            candles=candles
        )
        
        self.pools = bsl_pools + ssl_pools
        
        # Filter by minimum touches
        self.pools = [p for p in self.pools if p.touches >= self.min_touches]
        
        return self.pools
        
    def _cluster_liquidity(
        self,
        points: List[Tuple[int, float]],
        kind: str,
        candles: List[Candle]
    ) -> List[LiquidityPool]:
        """Cluster nearby liquidity points into pools"""
        if not points:
            return []
            
        clusters: Dict[float, LiquidityPool] = {}
        
        for idx, price in points:
            # Find matching cluster
            matched = False
            
            for cluster_price, pool in clusters.items():
                if abs(cluster_price - price) / cluster_price <= self.tolerance:
                    # Add to existing cluster
                    pool.touches += 1
                    pool.indices.append(idx)
                    pool.strength = self._calculate_pool_strength(pool, candles)
                    
                    # Check for EQH/EQL
                    if pool.touches >= 2 and pool.eq_type is None:
                        pool.eq_type = "EQH" if kind == "BUY_SIDE" else "EQL"
                        pool.liquidity_type = "EQUAL"
                        
                    matched = True
                    break
                    
            if not matched:
                # Create new cluster
                pool = LiquidityPool(
                    kind=kind,
                    price=price,
                    touches=1,
                    strength=10.0,
                    liquidity_type="SWING",
                    eq_type=None,
                    indices=[idx]
                )
                clusters[price] = pool
                
        return list(clusters.values())
        
    def _calculate_pool_strength(
        self,
        pool: LiquidityPool,
        candles: List[Candle]
    ) -> float:
        """
        Calculate liquidity pool strength (0-100)
        
        Factors:
        - Number of touches
        - Timeframe confluence
        - Recent price action
        - Volume (if available)
        """
        strength = 0.0
        
        # Touch count (max 40 points)
        strength += min(pool.touches * 15, 40)
        
        # EQH/EQL bonus (max 20 points)
        if pool.eq_type:
            strength += 20
            
        # Recency bonus (max 20 points)
        if pool.indices and candles:
            most_recent = max(pool.indices)
            recency = 1 - (len(candles) - most_recent - 1) / len(candles)
            strength += recency * 20
            
        # Timeframe confluence (max 20 points)
        strength += min(len(pool.timeframes) * 10, 20)
        
        return min(strength, 100.0)
        
    def detect_sweeps(
        self,
        candles: List[Candle],
        pools: Optional[List[LiquidityPool]] = None
    ) -> List[LiquiditySweep]:
        """
        Detect liquidity sweep events
        
        A sweep occurs when:
        - Price wicks above BSL then closes below
        - Price wicks below SSL then closes above
        
        Args:
            candles: List of Candle objects
            pools: Optional list of LiquidityPool objects
            
        Returns:
            List of LiquiditySweep objects
        """
        self.sweeps = []
        target_pools = pools if pools else self.pools
        
        if len(candles) < 3:
            return []
            
        for i in range(1, len(candles)):
            candle = candles[i]
            prev_candle = candles[i - 1]
            
            # Check each pool for sweep
            for pool in target_pools:
                if pool.swept:
                    continue
                    
                if pool.kind == "BUY_SIDE":
                    # Check for bullish sweep (price takes out highs)
                    sweep = self._detect_bullish_sweep(
                        candle=candle,
                        prev_candle=prev_candle,
                        pool=pool,
                        index=i
                    )
                    if sweep:
                        self.sweeps.append(sweep)
                        pool.swept = True
                        pool.sweep_index = i
                        pool.sweep_price = sweep.sweep_price
                        
                elif pool.kind == "SELL_SIDE":
                    # Check for bearish sweep (price takes out lows)
                    sweep = self._detect_bearish_sweep(
                        candle=candle,
                        prev_candle=prev_candle,
                        pool=pool,
                        index=i
                    )
                    if sweep:
                        self.sweeps.append(sweep)
                        pool.swept = True
                        pool.sweep_index = i
                        pool.sweep_price = sweep.sweep_price
                        
        return self.sweeps
        
    def _detect_bullish_sweep(
        self,
        candle: Candle,
        prev_candle: Candle,
        pool: LiquidityPool,
        index: int
    ) -> Optional[LiquiditySweep]:
        """Detect sweep of buy side liquidity"""
        # Price must take out the pool level
        if candle.high <= pool.price:
            return None
            
        sweep_price = candle.high
        sweep_size = sweep_price - pool.price
        
        # Check for rejection (close below pool or long upper wick)
        is_rejected = False
        rejection_kind = None
        
        if candle.close < pool.price:
            # Full rejection - close back below level
            is_rejected = True
            rejection_kind = "FALSE_BREAK"
        elif candle.upper_wick > candle.body * 1.5:
            # Strong upper wick shows rejection
            is_rejected = True
            rejection_kind = "WICK"
            
        if not is_rejected:
            return None
            
        # Calculate rejection strength
        rejection_strength = 0.0
        
        if rejection_kind == "FALSE_BREAK":
            rejection_strength = 50
            # More strength if close is far below pool
            distance_ratio = (pool.price - candle.close) / sweep_size if sweep_size > 0 else 0
            rejection_strength += min(distance_ratio * 30, 30)
        else:  # WICK
            rejection_strength = 40
            # More strength for longer wick
            wick_ratio = candle.upper_wick / candle.range if candle.range > 0 else 0
            rejection_strength += min(wick_ratio * 40, 40)
            
        # Check body direction
        if candle.close < candle.open:
            rejection_strength += 20
            
        sweep = LiquiditySweep(
            kind="BULLISH",  # Swept lows, expecting bullish reversal
            pool=pool,
            sweep_index=index,
            sweep_price=sweep_price,
            rejection_index=index,
            rejection_price=candle.close,
            sweep_size=sweep_size,
            rejection_strength=min(rejection_strength, 100.0),
            is_false_break=(rejection_kind == "FALSE_BREAK"),
            follow_through=False
        )
        
        # Check for follow-through on next candle
        if index + 1 < len([candle]):
            # Will be updated in subsequent analysis
            pass
            
        return sweep
        
    def _detect_bearish_sweep(
        self,
        candle: Candle,
        prev_candle: Candle,
        pool: LiquidityPool,
        index: int
    ) -> Optional[LiquiditySweep]:
        """Detect sweep of sell side liquidity"""
        # Price must take out the pool level
        if candle.low >= pool.price:
            return None
            
        sweep_price = candle.low
        sweep_size = pool.price - sweep_price
        
        # Check for rejection (close above pool or long lower wick)
        is_rejected = False
        rejection_kind = None
        
        if candle.close > pool.price:
            # Full rejection - close back above level
            is_rejected = True
            rejection_kind = "FALSE_BREAK"
        elif candle.lower_wick > candle.body * 1.5:
            # Strong lower wick shows rejection
            is_rejected = True
            rejection_kind = "WICK"
            
        if not is_rejected:
            return None
            
        # Calculate rejection strength
        rejection_strength = 0.0
        
        if rejection_kind == "FALSE_BREAK":
            rejection_strength = 50
            distance_ratio = (candle.close - pool.price) / sweep_size if sweep_size > 0 else 0
            rejection_strength += min(distance_ratio * 30, 30)
        else:  # WICK
            rejection_strength = 40
            wick_ratio = candle.lower_wick / candle.range if candle.range > 0 else 0
            rejection_strength += min(wick_ratio * 40, 40)
            
        if candle.close > candle.open:
            rejection_strength += 20
            
        sweep = LiquiditySweep(
            kind="BEARISH",  # Swept highs, expecting bearish reversal
            pool=pool,
            sweep_index=index,
            sweep_price=sweep_price,
            rejection_index=index,
            rejection_price=candle.close,
            sweep_size=sweep_size,
            rejection_strength=min(rejection_strength, 100.0),
            is_false_break=(rejection_kind == "FALSE_BREAK"),
            follow_through=False
        )
        
        return sweep
        
    def get_unswept_pools(
        self,
        pools: Optional[List[LiquidityPool]] = None
    ) -> List[LiquidityPool]:
        """Get all unswept liquidity pools"""
        target = pools if pools else self.pools
        return [p for p in target if not p.swept]
        
    def get_nearest_pool(
        self,
        current_price: float,
        kind: str,
        pools: Optional[List[LiquidityPool]] = None
    ) -> Optional[LiquidityPool]:
        """
        Get nearest liquidity pool of specified kind
        
        For BUY_SIDE: nearest above current price
        For SELL_SIDE: nearest below current price
        """
        target = pools if pools else self.pools
        
        if kind == "BUY_SIDE":
            valid = [p for p in target if p.kind == "BUY_SIDE" and p.price > current_price]
            if not valid:
                return None
            return min(valid, key=lambda p: p.price)
        else:
            valid = [p for p in target if p.kind == "SELL_SIDE" and p.price < current_price]
            if not valid:
                return None
            return max(valid, key=lambda p: p.price)
            
    def calculate_draw(
        self,
        current_price: float,
        pools: Optional[List[LiquidityPool]] = None
    ) -> Dict[str, float]:
        """
        Calculate magnetic draw towards liquidity pools
        
        Returns dict with:
        - bsl_draw: Distance to nearest buy side liquidity (%)
        - ssl_draw: Distance to nearest sell side liquidity (%)
        - net_draw: Net bias (positive = bullish draw, negative = bearish)
        """
        target = pools if pools else self.pools
        
        bsl_pools = [p for p in target if p.kind == "BUY_SIDE" and not p.swept]
        ssl_pools = [p for p in target if p.kind == "SELL_SIDE" and not p.swept]
        
        bsl_draw = 0.0
        ssl_draw = 0.0
        
        if bsl_pools:
            nearest_bsl = min(bsl_pools, key=lambda p: abs(p.price - current_price))
            bsl_draw = (nearest_bsl.price - current_price) / current_price * 100
            
        if ssl_pools:
            nearest_ssl = max(ssl_pools, key=lambda p: abs(p.price - current_price))
            ssl_draw = (current_price - nearest_ssl.price) / current_price * 100
            
        net_draw = bsl_draw - ssl_draw
        
        return {
            "bsl_draw": bsl_draw,
            "ssl_draw": ssl_draw,
            "net_draw": net_draw,
            "nearest_bsl": min([p.price for p in bsl_pools]) if bsl_pools else None,
            "nearest_ssl": max([p.price for p in ssl_pools]) if ssl_pools else None
        }
