import pytest
from market_phase_engine import MarketPhaseEngine

@pytest.fixture
def market_phase_engine():
    return MarketPhaseEngine()

def test_market_phase_detection(market_phase_engine):
    # Mock data from existing script
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

    result = market_phase_engine.detect(
        structure=mock_structure,
        trend=mock_trend,
        liquidity_sweep=mock_liquidity_sweep,
        fvg=mock_fvg,
        orderblocks=mock_orderblocks,
        premium_discount=mock_premium_discount,
        mtf=mock_mtf
    )

    assert result['phase'] == 'Manipulation'
    assert result['phase_confidence'] == 70
    assert result['phase_strength'] == 'STRONG'
    assert result['phase_score'] == 96
    assert result['mtf_alignment'] == 100
    assert 'Liquidity Sweep' in result['phase_indicators']
