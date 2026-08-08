import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.candle import Candle
from timing import closed_htf_candles, TF_PERIOD_MS
from backtest_runner import _window_up_to


def _candle(t, o=100, h=101, l=99, c=100):
    return Candle(time=t, open=o, high=h, low=l, close=c, volume=1.0)


def test_htf_period_map_is_complete():
    assert set(TF_PERIOD_MS) == {"15m", "1h", "4h", "1d", "1w"}
    assert TF_PERIOD_MS["1h"] == 3600_000
    assert TF_PERIOD_MS["1d"] == 86400_000


def test_closed_htf_excludes_still_forming_candle():
    # 1h mumları: 21:00, 22:00 (kapanmış), 23:00 (henüz oluşmakta)
    # Referans 23:45 → 23:00 mumu (23:00+1h=24:00 > 23:45) DAHİL EDİLMEMELİ.
    candles = [
        _candle(21 * 3600_000),
        _candle(22 * 3600_000),
        _candle(23 * 3600_000),
        _candle(24 * 3600_000),
    ]
    ref = 23 * 3600_000 + 45 * 60_000  # 23:45
    out = closed_htf_candles(candles, ref, "1h")
    times = [c.time for c in out]
    assert 21 * 3600_000 in times
    assert 22 * 3600_000 in times
    assert 23 * 3600_000 not in times, "oluşmakta olan 1h mumu analize girmemeli"
    assert 24 * 3600_000 not in times


def test_closed_htf_forms_at_reference():
    # 1h mumu 22:00'de kapanır (22:00 + 1h = 23:00). Referans tam 23:00 ise
    # 22:00 mumu KAPANMIŞ sayılır (23:00 + 1h = 24:00 > 23:00, kendisi hariç).
    candles = [_candle(22 * 3600_000), _candle(23 * 3600_000)]
    out = closed_htf_candles(candles, 23 * 3600_000, "1h")
    assert [c.time for c in out] == [22 * 3600_000]


def test_no_timeframe_falls_back_to_time_filter():
    candles = [_candle(1000), _candle(2000)]
    out = closed_htf_candles(candles, 1500, None)
    assert [c.time for c in out] == [1000]


def test_backtest_runner_uses_same_rule():
    # backtest_runner._window_up_to, timing.closed_htf_candles ile aynı sonucu verir.
    candles = [
        _candle(21 * 3600_000),
        _candle(22 * 3600_000),
        _candle(23 * 3600_000),
    ]
    ref = 23 * 3600_000 + 30 * 60_000
    assert [c.time for c in _window_up_to(candles, ref, "1h")] == [21 * 3600_000, 22 * 3600_000]
    assert [c.time for c in _window_up_to(candles, ref, None)] == [21 * 3600_000, 22 * 3600_000, 23 * 3600_000]


def test_empty_inputs():
    assert closed_htf_candles([], 123, "1h") == []
    assert closed_htf_candles(None, 123, "1h") == []