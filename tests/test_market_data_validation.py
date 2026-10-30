import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.candle import Candle
from engine import AtlasEngine


def _candle(timestamp=0, open_price=100.0, high=101.0, low=99.0, close=100.5, volume=10.0):
    return Candle(timestamp, open_price, high, low, close, volume)


def _data(series=None):
    candles = series if series is not None else [_candle()]
    return {"15m": candles, "1h": candles, "4h": candles, "1d": candles, "1w": candles}


def test_market_data_validation_accepts_valid_ordered_ohlcv():
    AtlasEngine.__new__(AtlasEngine)._validate_market_data(
        _data([_candle(0), _candle(900_000), _candle(1_800_000)])
    )


@pytest.mark.parametrize(
    "bad_candle, message",
    [
        (_candle(high=98.0), "Inconsistent OHLC prices"),
        (_candle(close=float("nan")), "Non-finite OHLCV value"),
        (_candle(volume=float("inf")), "Non-finite OHLCV value"),
        (_candle(open_price=0.0), "Invalid OHLCV range"),
        (_candle(volume=-1.0), "Invalid OHLCV range"),
        (_candle(timestamp=-1), "Invalid candle timestamp"),
    ],
)
def test_market_data_validation_rejects_invalid_candles(bad_candle, message):
    with pytest.raises(ValueError, match=message):
        AtlasEngine.__new__(AtlasEngine)._validate_market_data(_data([bad_candle]))


def test_market_data_validation_rejects_duplicate_or_unsorted_timestamps():
    candles = [_candle(900_000), _candle(900_000)]
    with pytest.raises(ValueError, match="strictly increasing"):
        AtlasEngine.__new__(AtlasEngine)._validate_market_data(_data(candles))


def test_market_data_validation_rejects_missing_required_timeframe():
    data = _data()
    data["4h"] = []
    with pytest.raises(ValueError, match="4h"):
        AtlasEngine.__new__(AtlasEngine)._validate_market_data(data)


def test_market_data_validation_rejects_malformed_candle_object():
    data = _data([object()])
    with pytest.raises(ValueError, match="Malformed OHLCV candle"):
        AtlasEngine.__new__(AtlasEngine)._validate_market_data(data)
