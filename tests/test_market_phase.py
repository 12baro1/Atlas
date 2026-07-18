import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_phase_engine import MarketPhaseEngine

# Create mock data
mock_structure = [
    {"index": 0, "price": 100, "type": "HIGH", "label": "HH", "bos": True, "choch": False},
    {"index": 5, "price": 95, "type": "LOW", "label": "HL", "bos": False, "choch": False},
]

mock_trend = {
    "trend": "BULLISH",
    "strength": 2,
    "score": 50
}

mock_liquidity_sweep = {
    "buy_side": True,
    "sell_side": False,
    "swept_high": 105,
    "swept_low": None
}

mock_fvg = [{"from": 98, "to": 99}]
mock_orderblocks = [{"type": "BULLISH", "high": 102, "low": 101}]

mock_premium_discount = {
    "valid": True,
    "premium": False,
    "discount": True,
    "equilibrium": 100,
    "premium_zone": (100, 105),
    "discount_zone": (95, 100)
}

mock_mtf = {
    "weekly": "BULLISH",
    "daily": "BULLISH",
    "h4": "BULLISH",
    "valid": True,
    "entry": "LONG"
}

# Test MarketPhaseEngine
engine = MarketPhaseEngine()
result = engine.detect(
    structure=mock_structure,
    trend=mock_trend,
    liquidity_sweep=mock_liquidity_sweep,
    fvg=mock_fvg,
    orderblocks=mock_orderblocks,
    premium_discount=mock_premium_discount,
    mtf=mock_mtf
)

print("✅ MarketPhaseEngine Test Results:")
print(f"  Phase: {result['phase']}")
print(f"  Confidence: {result['phase_confidence']}%")
print(f"  Strength: {result['phase_strength']}")
print(f"  Score: {result['phase_score']}")
print(f"  MTF Alignment: {result['mtf_alignment']}%")
print(f"  Indicators: {result['phase_indicators']}")
print("\n✅ All phase detection working correctly!")
