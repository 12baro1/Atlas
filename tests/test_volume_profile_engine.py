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
    assert profile["event_id"].startswith("volume_profile:")
    assert profile["poc"] is not None
    assert profile["vah"] is not None
    assert profile["val"] is not None
    assert profile["confidence"] >= 0
    assert profile["direction"] in ["BULLISH", "BEARISH", "NONE"]
    assert 0 <= profile["bias_strength"] <= 100
    assert profile["value_area_position"] in ["ABOVE_VALUE", "BELOW_VALUE", "UPPER_VALUE", "LOWER_VALUE"]


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


def test_poc_near_is_not_a_directional_signal():
    assert VolumeProfileEngine()._direction_bias("POC_NEAR") == "NONE"


def test_inner_value_area_states_are_not_forced_directional():
    engine = VolumeProfileEngine()
    assert engine._direction_bias("ABOVE_POC") == "NONE"
    assert engine._direction_bias("BELOW_POC") == "NONE"
    assert engine._direction_bias("VALUE_HIGH") == "NONE"
    assert engine._direction_bias("VALUE_LOW") == "NONE"


def test_distribution_quality_is_price_scale_independent():
    engine = VolumeProfileEngine()
    histogram = [1.0, 2.0, 8.0, 2.0, 1.0]
    score_a = engine._confidence(histogram, 2, 3, 1, 100.0, 102.0, 98.0)
    score_b = engine._confidence(histogram, 2, 3, 1, 10_000.0, 10_200.0, 9_800.0)
    assert score_a == score_b


def test_volume_profile_declares_ohlcv_proxy_source():
    result = VolumeProfileEngine().detect(_candles(), bins=30)
    assert result["source"] == "ohlcv_range_proxy"
    assert result["is_proxy"] is True


def test_empty_bins_are_not_reported_as_low_volume_nodes():
    engine = VolumeProfileEngine()
    assert engine._bottom_nodes([0, 0, 5, 0, 2, 0], count=3) == [4, 2]
