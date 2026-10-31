import sys
import os

import pytest

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
        _tl(100.0, l=100.1, h=101.5, cl=100.5),   # TP1(101) kapanır
        _tl(100.5, l=100.2, h=102.5, cl=102.0),  # TP2(102) kapanır
    ]
    out = simulate_trade_partial(100.0, 99.0, [101.0, 102.0], candles, "LONG")
    assert out["result"] == "WIN"
    assert out["tp"] == 2
    assert abs(out["net_rr"] - 1.5) < 1e-6


def test_partial_three_levels_runs_to_tp3():
    candles = [
        _tl(100.0, l=100.1, h=101.5),   # TP1 %33.3 → +1/3R
        _tl(100.5, l=101.2, h=102.5),  # TP2 %33.3 → +2/3R
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
        _tl(100.0, l=100.1, h=101.0, cl=100.5),  # yalnız TP1 kapanır
    ]
    out = simulate_trade_partial(100.0, 98.0, [101.0, 102.0], candles, "LONG")
    assert out["result"] == "OPEN"
    assert out["net_rr"] == 0.0
def test_runner_applies_round_trip_fee_rate_once():
    runner = BacktestRunner(fee_rate=0.002, partial_exits=False)
    candles = [_candle(1, 100.0, 101.5, 100.1, 101.0)]
    result = {
        "decision": {"action": "EXECUTE"},
        "signal": {"signal": "LONG"},
        "risk": {"entry": 100.0, "stop_loss": 99.0, "tp1": 101.0, "tp2": None, "tp3": None},
    }

    trade = runner._to_trade(result, candles, entry_index=0)

    # 0.2% round-trip cost at entry 100 = 0.20 price units = 0.20R.
    assert trade is not None
    assert trade["net_rr"] == 0.8



def test_partial_tp1_and_breakeven_in_same_candle_does_not_count_tp2():
    # OHLC cannot prove TP2 came before the newly moved breakeven stop.
    candle = _tl(10.5, o=10.0, h=12.5, l=9.9, cl=10.5)
    out = simulate_trade_partial(10.0, 9.0, [11.0, 12.0], [candle], "LONG")
    assert out["result"] == "WIN"
    assert out["tp"] == 1
    assert out["net_rr"] == 0.5


def test_limit_order_is_not_filled_without_price_touch():
    runner = BacktestRunner(partial_exits=False)
    candles = [_candle(1, 100.0, 101.0, 98.0, 99.0)]
    result = {
        "decision": {"action": "EXECUTE"},
        "signal": {"signal": "LONG"},
        "risk": {"entry": 95.0, "stop_loss": 90.0, "tp1": 100.0, "tp2": 105.0, "tp3": 110.0},
        "analysis": {"entry": {"entry_type": "LIMIT"}},
    }
    assert runner._to_trade(result, candles, entry_index=0) is None
    stats = runner.statistics()
    assert stats["candidate_signals"] == 1
    assert stats["unfilled_limits"] == 1
    assert stats["total"] == 0


def test_limit_order_fills_only_after_touching_level():
    runner = BacktestRunner(partial_exits=False)
    candles = [
        _candle(1, 97.0, 99.0, 94.0, 96.0),
        _candle(2, 96.0, 101.5, 95.5, 101.0),
    ]
    result = {
        "decision": {"action": "EXECUTE"},
        "signal": {"signal": "LONG"},
        "risk": {"entry": 95.0, "stop_loss": 90.0, "tp1": 100.0, "tp2": 105.0, "tp3": 110.0},
        "analysis": {"entry": {"entry_type": "LIMIT"}},
    }
    trade = runner._to_trade(result, candles, entry_index=0)
    assert trade is not None
    assert trade["entry_type"] == "LIMIT"
    assert trade["entry"] == 95.0
    assert trade["entry_index"] == 0


def test_market_order_uses_next_candle_open_as_fill_price():
    runner = BacktestRunner(partial_exits=False)
    candles = [_candle(1, 101.0, 103.5, 100.5, 103.0)]
    result = {
        "decision": {"action": "EXECUTE"},
        "signal": {"signal": "LONG"},
        "risk": {"entry": 100.0, "stop_loss": 99.0, "tp1": 103.0, "tp2": 104.0, "tp3": 105.0},
        "analysis": {"entry": {"entry_type": "MARKET"}},
    }
    trade = runner._to_trade(result, candles, entry_index=0)
    assert trade is not None
    assert trade["entry"] == 101.0


def test_market_order_is_rejected_when_gap_has_already_crossed_tp1():
    runner = BacktestRunner(partial_exits=False)
    candles = [_candle(1, 102.0, 103.0, 101.5, 102.5)]
    result = {
        "decision": {"action": "EXECUTE"},
        "signal": {"signal": "LONG"},
        "risk": {"entry": 100.0, "stop_loss": 99.0, "tp1": 101.0, "tp2": 102.0, "tp3": 103.0},
        "analysis": {"entry": {"entry_type": "MARKET"}},
    }
    assert runner._to_trade(result, candles, entry_index=0) is None



def test_backtest_numeric_parser_rejects_non_finite_values():
    from backtest_runner import _num
    assert _num(float("nan")) is None
    assert _num(float("inf")) is None



def test_runner_exposes_gross_profit_and_loss_components():
    runner = BacktestRunner()
    runner._record({"_w": True, "net_rr": 2.0, "_levels": [1]})
    runner._record({"_w": False, "net_rr": -1.0, "_levels": []})
    stats = runner.statistics()
    assert stats["gross_profit_rr"] == 2.0
    assert stats["gross_loss_rr"] == 1.0
    assert stats["profit_factor"] == 2.0



def test_backtest_reports_unresolved_open_trade_separately():
    runner = BacktestRunner(partial_exits=False)
    candles = [_candle(1, 100.0, 105.0, 95.0, 102.0)]
    result = {
        "decision": {"action": "EXECUTE"},
        "signal": {"signal": "LONG"},
        "risk": {"entry": 100.0, "stop_loss": 90.0, "tp1": 110.0, "tp2": 120.0, "tp3": 130.0},
        "analysis": {"entry": {"entry_type": "MARKET"}},
    }
    assert runner._to_trade(result, candles, entry_index=0) is None
    stats = runner.statistics()
    assert stats["candidate_signals"] == 1
    assert stats["open_trades"] == 1
    assert stats["total"] == 0



def test_runner_counts_final_candidate_without_followup_candle():
    candles = _rising_series(301)

    def fake_analyze(window):
        if len(window["15m"]) == 301:
            return {
                "decision": {"action": "EXECUTE"},
                "signal": {"signal": "LONG"},
                "risk": {
                    "entry": 500.0,
                    "stop_loss": 400.0,
                    "tp1": 600.0,
                    "tp2": 700.0,
                    "tp3": 800.0,
                },
                "analysis": {"entry": {"entry_type": "MARKET"}},
            }
        return None

    stats = BacktestRunner(analyze_fn=fake_analyze).run({"15m": candles})

    assert stats["candidate_signals"] == 1
    assert stats["no_followup_data"] == 1
    assert stats["total"] == 0


def test_intrabar_limit_fill_does_not_count_target_touched_before_fill():
    runner = BacktestRunner(partial_exits=False)
    # The high reaches TP before price later trades down to the LONG limit.
    # OHLC cannot prove a second TP touch after the fill, so result stays OPEN.
    candles = [_candle(1, 100.0, 105.0, 94.0, 95.0)]
    result = {
        "decision": {"action": "EXECUTE"},
        "signal": {"signal": "LONG"},
        "risk": {"entry": 95.0, "stop_loss": 90.0, "tp1": 101.0, "tp2": 103.0, "tp3": 104.0},
        "analysis": {"entry": {"entry_type": "LIMIT"}},
    }
    assert runner._to_trade(result, candles, entry_index=0) is None
    stats = runner.statistics()
    assert stats["total"] == 0
    assert stats["open_trades"] == 1


def test_intrabar_limit_fill_candle_stop_is_counted_conservatively():
    runner = BacktestRunner(partial_exits=False)
    candles = [_candle(1, 100.0, 102.0, 89.0, 91.0)]
    result = {
        "decision": {"action": "EXECUTE"},
        "signal": {"signal": "LONG"},
        "risk": {"entry": 95.0, "stop_loss": 90.0, "tp1": 101.0, "tp2": 103.0, "tp3": 104.0},
        "analysis": {"entry": {"entry_type": "LIMIT"}},
    }
    trade = runner._to_trade(result, candles, entry_index=0)
    assert trade is not None
    assert trade["result"] == "LOSS"
    assert trade["net_rr"] < -1.0



def test_partial_tp_uses_configured_normalized_exit_weights():
    candles = [
        _tl(100.0, o=100.0, h=101.2, l=100.1, cl=101.0, t=1),
        _tl(102.0, o=101.2, h=102.2, l=101.1, cl=102.0, t=2),
        _tl(102.0, o=102.0, h=103.2, l=101.5, cl=103.0, t=3),
    ]
    out = simulate_trade_partial(
        entry=100.0,
        stop_loss=99.0,
        targets=[101.0, 102.0, 103.0],
        future_candles=candles,
        direction="LONG",
        tp_weights={"tp1": 0.5, "tp2": 0.3, "tp3": 0.2},
    )

    assert out["result"] == "WIN"
    assert out["tp"] == 3
    assert out["net_rr"] == pytest.approx(1.7, abs=1e-4)



def test_partial_tp2_moves_remaining_stop_to_tp1():
    candles = [
        _tl(100.0, o=100.0, h=101.2, l=100.1, cl=101.0, t=1),
        _tl(102.0, o=101.2, h=102.2, l=101.2, cl=102.0, t=2),
        _tl(101.0, o=101.0, h=101.5, l=100.9, cl=101.0, t=3),
    ]

    out = simulate_trade_partial(
        entry=100.0,
        stop_loss=99.0,
        targets=[101.0, 102.0, 103.0],
        future_candles=candles,
        direction="LONG",
    )

    assert out["result"] == "WIN"
    assert out["tp"] == 2
    assert out["levels"] == [1, 2]
    assert out["net_rr"] == pytest.approx(4.0 / 3.0, abs=1e-4)


def test_partial_tp2_moves_short_stop_to_tp1():
    candles = [
        _tl(100.0, o=100.0, h=99.9, l=98.8, cl=99.0, t=1),
        _tl(98.0, o=98.8, h=98.8, l=97.8, cl=98.0, t=2),
        _tl(99.0, o=99.0, h=99.1, l=98.5, cl=99.0, t=3),
    ]

    out = simulate_trade_partial(
        entry=100.0,
        stop_loss=101.0,
        targets=[99.0, 98.0, 97.0],
        future_candles=candles,
        direction="SHORT",
    )

    assert out["result"] == "WIN"
    assert out["tp"] == 2
    assert out["levels"] == [1, 2]
    assert out["net_rr"] == pytest.approx(4.0 / 3.0, abs=1e-4)
