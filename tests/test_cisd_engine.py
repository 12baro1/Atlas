import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cisd_engine import CISDEngine
from core.candle import Candle


def _candle(index, open_price, high_price, low_price, close_price):
    return Candle(
        time=1_700_000_000_000 + (index * 60_000),
        open=open_price,
        high=high_price,
        low=low_price,
        close=close_price,
        volume=100.0,
    )


def test_detects_bullish_cisd_change():
    engine = CISDEngine()

    candles = []
    # Önce sell delivery
    for i in range(6):
        candles.append(_candle(i, 100 - i, 101 - i, 98 - i, 99 - i))
    # Sonra güçlü buy delivery
    for i in range(6, 12):
        base = 94 + (i - 6)
        candles.append(_candle(i, base, base + 2.5, base - 0.6, base + 2.2))

    structure = [{"bos": True, "choch": False, "direction": "BULLISH"}]
    liquidity_sweep = {"sell_side": True, "buy_side": False}
    market_phase = {"phase": "Expansion"}
    smt = {"active": True, "direction": "BULLISH", "confidence": 78}

    result = engine.detect(candles, structure, liquidity_sweep, market_phase, smt, "15m")

    assert result["active"] is True
    assert result["direction"] == "BULLISH"
    assert 0 <= result["confidence"] <= 100


def test_detect_multi_returns_best_event():
    engine = CISDEngine()

    bullish_candles = []
    for i in range(6):
        bullish_candles.append(_candle(i, 50 - i, 51 - i, 48 - i, 49 - i))
    for i in range(6, 12):
        base = 44 + (i - 6)
        bullish_candles.append(_candle(i, base, base + 2.8, base - 0.5, base + 2.4))

    payload = {
        "15m": {
            "candles": bullish_candles,
            "structure": [{"bos": True, "direction": "BULLISH"}],
            "liquidity_sweep": {"sell_side": True, "buy_side": False},
            "market_phase": {"phase": "Expansion"},
            "smt": {"active": True, "direction": "BULLISH"},
        }
    }

    result = engine.detect_multi(payload)

    assert result["active"] is True
    assert result["best"] is not None
    assert result["best"]["timeframe"] == "15m"
