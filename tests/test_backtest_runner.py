import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.candle import Candle
from backtest_runner import simulate_trade, simulate_trade_partial, BacktestRunner


def _candle(t, o, h, l, cl):
    return Candle(time=t, open=o, high=h, low=l, close=cl, volume=1.0)


def _rising_series(n=800, start_price=100.0):
    return [
        _candle(1000 + i * 60, start_price + i, start_price + i + 2, start_price + i - 2, start_price + i + 1)
        for i in range(n)
    ]


def test_simulate_long_hits_tp1_before_unknown():
    candles = [_candle(1, 10.2, 11.0, 10.1, 11.0)]
    out = simulate_trade(10, 9, [11, 12, 13], candles, "LONG")
    assert out["result"] == "WIN"
    assert out["tp"] == 1
    assert out["net_rr"] == 1.0


def test_simulate_long_stop_loss_first():
    candles = [_candle(1, 10.0, 10.2, 8.5, 8.6)]
    out = simulate_trade(10, 9, [11, 12], candles, "LONG")
    assert out["result"] == "LOSS"
    assert out["tp"] == 0
    assert out["net_rr"] == -1.0


def test_simulate_short_hits_tp():
    candles = [_candle(1, 9.6, 10.0, 8.9, 9.0)]
    out = simulate_trade(10, 11, [9, 8], candles, "SHORT")
    assert out["result"] == "WIN"
    assert out["tp"] == 1


def test_simulate_no_touch_is_open():
    candles = [_candle(1, 10.5, 10.6, 10.1, 10.2)]
    out = simulate_trade(10, 9, [12, 13], candles, "LONG")
    assert out["result"] == "OPEN"
    assert out["tp"] == 0


def test_runner_counts_and_reports_expectancy():
    candles = _rising_series(800)

    def fake_analyze(window):
        n = len(window["15m"])
        if n == 400:
            return {
                "decision": {"action": "EXECUTE"},
                "signal": {"signal": "LONG"},
                "risk": {"entry": 500.0, "stop_loss": 400.0, "tp1": 600.0, "tp2": 700.0, "tp3": 800.0},
            }
        return None

    runner = BacktestRunner(analyze_fn=fake_analyze)
    stats = runner.run({"15m": candles})
    assert stats["total"] == 1
    assert stats["wins"] == 1
    assert stats["winrate"] == 100.0
    assert stats["expectancy"] > 0
    # Yükselen seri kısmi modelde TP1→TP2→TP3'ü de sırayla vurur.
    assert stats["tp1"] == 1
    assert stats["tp3"] == 1


def test_runner_ignores_skip_and_missing_risk():
    candles = _rising_series(500)

    def fake_analyze(window):
        n = len(window["15m"])
        if n == 400:
            # wait signal -> ignored
            return {"decision": {"action": "SKIP"}, "signal": {"signal": "WAIT"}, "risk": {}}
        return None

    runner = BacktestRunner(analyze_fn=fake_analyze)
    stats = runner.run({"15m": candles})
    assert stats["total"] == 0


# ---------------------------------------------------------------------------
# KISMİ TP/SL ÇIKIŞ MODELLERİ
# ---------------------------------------------------------------------------

def _tl(price, o=None, h=None, l=None, cl=None, t=1):
    """Tek mum yardımcı. Varsayılan high/low price civarında."""
    o = price if o is None else o
    h = price + 0.2 if h is None else h
    l = price - 0.2 if l is None else l
    cl = price if cl is None else cl
    return Candle(time=t, open=o, high=h, low=l, close=cl, volume=1.0)


def test_partial_tp1_then_sl_at_breakeven():
    """TP1 (%50) kapanır, kalanın stopu breakeven'e taşınır; kalan pozisyon
    breakeven'de (0R) kapanır → net = 0.5*1 + 0.5*0 = +0.5R."""
    candles = [
        _tl(10.0, h=11.1, l=10.1, cl=10.6),  # TP1(11.0) vurulur, SL breakeven 10.0
        _tl(10.5, h=10.6, l=9.9, cl=10.0),   # kalan breakeven'den çıkar (0R)
    ]
    out = simulate_trade_partial(10.0, 9.0, [11.0, 12.0], candles, "LONG")
    assert out["result"] == "WIN"
    assert out["tp"] == 1
    assert out["net_rr"] == 0.5


def test_partial_tp1_then_tp2_scenario():
    """TP scenario: TP1 kapanır, ardından TP2'ye devam → net = 0.5*1+0.5*2=+1.5R."""
    candles = [
        _tl(100.0, l=99.5, h=101.5, cl=100.5),   # TP1(101) kapanır
        _tl(100.5, l=100.2, h=102.5, cl=102.0),  # TP2(102) kapanır
    ]
    out = simulate_trade_partial(100.0, 99.0, [101.0, 102.0], candles, "LONG")
    assert out["result"] == "WIN"
    assert out["tp"] == 2
    assert abs(out["net_rr"] - 1.5) < 1e-6


def test_partial_three_levels_runs_to_tp3():
    candles = [
        _tl(100.0, l=99.4, h=101.5),   # TP1 %33.3 → +1/3R
        _tl(100.5, l=100.2, h=102.5),  # TP2 %33.3 → +2/3R
        _tl(101.5, l=101.2, h=104.5),  # TP3 %33.3 → +4/3R
    ]
    out = simulate_trade_partial(100.0, 99.0, [101.0, 102.0, 104.0], candles, "LONG")
    assert out["result"] == "WIN"
    assert out["tp"] == 3
    assert abs(out["net_rr"] - (1.0 / 3 + 2.0 / 3 + 4.0 / 3)) < 1e-3


def test_partial_first_touch_is_stop_loss():
    """Herhangi bir TP'den önce SL vurulur → tüm pozisyon -1R."""
    candles = [_tl(100.0, l=97.0, h=100.0, cl=98.0)]
    out = simulate_trade_partial(100.0, 99.0, [103.0, 104.0], candles, "LONG")
    assert out["result"] == "LOSS"
    assert out["tp"] == 0
    assert out["net_rr"] == -1.0


def test_partial_remaining_open_returns_open():
    # Pencere kapanmadan tüm pozisyon kapanmadı → istatistiğe girmez.
    candles = [
        _tl(100.0, l=99.0, h=101.0, cl=100.5),  # yalnız TP1 kapanır
    ]
    out = simulate_trade_partial(100.0, 98.0, [101.0, 102.0], candles, "LONG")
    assert out["result"] == "OPEN"
    assert out["net_rr"] == 0.0