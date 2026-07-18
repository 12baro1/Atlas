import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.candle import Candle
from institutional_engine import InstitutionalAnalysisEngine


def _candles():
    candles = []
    base_time = 1_700_000_000_000
    price = 100.0

    for index in range(24):
        open_price = price
        close_price = price + (0.18 if index % 3 != 0 else -0.05)
        high = max(open_price, close_price) + 0.35
        low = min(open_price, close_price) - 0.25
        volume = 140 + (index % 6) * 15
        candles.append(
            Candle(
                time=base_time + index * 60_000,
                open=open_price,
                high=high,
                low=low,
                close=close_price,
                volume=volume,
            )
        )
        price = close_price

    candles[-1] = Candle(
        time=base_time + 23 * 60_000,
        open=price - 0.2,
        high=price + 1.2,
        low=price - 0.4,
        close=price - 0.1,
        volume=260,
    )

    return candles


def test_institutional_engine_returns_full_analysis_bundle():
    engine = InstitutionalAnalysisEngine()

    result = engine.analyze(
        {
            "15m": _candles(),
            "open_interest": [1000, 1010, 1018, 1025],
            "funding_rate": [0.002, 0.003, 0.004],
            "market_breadth": {"advancers": 18, "decliners": 10},
            "peer_assets": {
                "BTC": {"candles": _candles()},
                "ETH": {"candles": _candles()},
            },
            "positions": [{"size": 0.15, "leverage": 2.0}],
            "correlation_risk": 0.18,
            "macro": {"bias": "LONG", "confidence": 72},
            "news": {"severity": 1, "bias": "NONE"},
        }
    )

    assert result["active"] is True
    assert result["vwap"] is not None
    assert result["market_regime"]["name"] in ["EXPANSION", "TRENDING_UP", "TRENDING_DOWN", "RANGING", "MEAN_REVERSION"]
    assert result["execution_quality"]["score"] >= 0
    assert result["ai_confidence"] >= 0
    assert result["adaptive_position_sizing"]["factor"] >= 0.7
    assert result["institutional_flow"]["direction"] in ["LONG", "SHORT", "NONE"]
