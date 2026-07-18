import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.candle import Candle
from volume_profile_engine import VolumeProfileEngine


def _candles(count=60, base=100.0):
    data = []
    t0 = 1_700_000_000_000
    for i in range(count):
        drift = (i % 12) * 0.08
        open_price = base + drift
        close_price = open_price + (0.12 if i % 2 == 0 else -0.07)
        high = max(open_price, close_price) + 0.25
        low = min(open_price, close_price) - 0.22
        volume = 120 + (i % 9) * 12
        data.append(
            Candle(
                time=t0 + i * 60_000,
                open=open_price,
                high=high,
                low=low,
                close=close_price,
                volume=volume,
            )
        )
    return data


def test_detect_returns_key_levels():
    engine = VolumeProfileEngine()
    profile = engine.detect(_candles(), bins=30)

    assert profile["active"] is True
    assert profile["poc"] is not None
    assert profile["vah"] is not None
    assert profile["val"] is not None
    assert profile["confidence"] >= 0


def test_detect_multi_returns_direction_and_best():
    engine = VolumeProfileEngine()
    payload = {
        "15m": _candles(60, base=100),
        "1h": _candles(60, base=101),
        "4h": _candles(60, base=102),
        "1d": _candles(60, base=103),
    }

    result = engine.detect_multi(payload)

    assert result["active"] is True
    assert result["best"] is not None
    assert result["direction"] in ["BULLISH", "BEARISH", "NONE"]
