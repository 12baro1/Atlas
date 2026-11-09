from core.candle import Candle
from timing import closed_htf_candles


def _candle(timestamp):
    return Candle(time=timestamp, open=100, high=102, low=99, close=101, volume=10)


def test_htf_candle_is_available_exactly_at_close_boundary():
    candles = [_candle(0), _candle(3_600_000)]
    assert closed_htf_candles(candles, 3_600_000, "1h") == [candles[0]]


def test_htf_candle_is_not_available_one_millisecond_before_close():
    candles = [_candle(0)]
    assert closed_htf_candles(candles, 3_599_999, "1h") == []


def test_future_htf_candle_is_never_included():
    candles = [_candle(3_600_000)]
    assert closed_htf_candles(candles, 3_600_000, "1h") == []


def test_unknown_timeframe_keeps_only_candles_not_after_reference():
    candles = [_candle(0), _candle(1_000), _candle(2_000)]
    assert closed_htf_candles(candles, 1_000, "unknown") == candles[:2]


def test_unsorted_htf_rows_are_filtered_and_returned_chronologically():
    candles = [_candle(7_200_000), _candle(0), _candle(3_600_000)]
    result = closed_htf_candles(candles, 7_200_000, "1h")
    assert [candle.time for candle in result] == [0, 3_600_000]


def test_invalid_reference_time_fails_closed():
    assert closed_htf_candles([_candle(0)], "not-a-timestamp", "1h") == []
