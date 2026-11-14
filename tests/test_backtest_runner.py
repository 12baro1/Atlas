import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.candle import Candle
from backtest_runner import simulate_trade, simulate_trade_partial, BacktestRunner
from config import Config


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



def test_partial_tp1_same_candle_breakeven_close_matches_journal():
    # trade_journal ile birebir aynı mum mantığı: TP1 dolduğunda taşınan
    # breakeven stopu bu mumun aralığındaysa kalan pay AYNI MUMDA kapanır
    # (OHLC mum içi sırayı kanıtlayamaz → konservatif) ve TP2 sayılmaz.
    first = _tl(10.5, o=10.0, h=12.5, l=9.9, cl=10.5)
    second = _tl(10.0, o=10.5, h=10.6, l=9.9, cl=10.0)
    out = simulate_trade_partial(10.0, 9.0, [11.0, 12.0], [first, second], "LONG")
    assert out["result"] == "WIN"
    assert out["tp"] == 1
    assert out["net_rr"] == 0.5
    assert out["exit_reason"] == "TRAILING_STOP"
    assert out["exit_offset"] == 0
    assert out["exit_price"] == 10.0


def test_partial_tp2_same_candle_with_tp1_stop_inside_range():
    # TP1 + TP2 aynı mumda (journal sıralı dolum kuralı); taşınan TP1 stopu
    # mum aralığında olsa da kalan pay 0 olduğundan pozisyon TP2'de kapanır.
    candle = _tl(11.0, o=10.0, h=12.5, l=10.5, cl=12.0)
    out = simulate_trade_partial(10.0, 9.0, [11.0, 12.0], [candle], "LONG")
    assert out["result"] == "WIN"
    assert out["tp"] == 2
    assert out["net_rr"] == 1.5
    assert out["exit_reason"] == "TP2"
    assert out["exit_offset"] == 0


def test_limit_order_is_not_filled_without_price_touch():
    runner = BacktestRunner(partial_exits=False)
    candles = [_candle(1, 100.0, 101.0, 98.0, 99.0)]
    result = {
        "decision": {"action": "EXECUTE"},
        "signal": {"signal": "LONG"},
        "risk": {"entry": 95.0, "stop_loss": 90.0, "tp1": 105.0, "tp2": 110.0, "tp3": 115.0},
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
        _tl(100.0, o=99.8, h=99.9, l=98.8, cl=99.0, t=1),
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



def test_sparse_tp2_tp3_backtest_does_not_treat_tp2_as_tp1():
    candles = [
        _tl(100.0, o=100.0, h=98.8, l=98.0, cl=98.5, t=1),
    ]
    out = simulate_trade_partial(
        entry=100.0,
        stop_loss=101.0,
        targets=[None, 98.0, 97.0],
        future_candles=candles,
        direction="SHORT",
    )

    # The trade is still open after TP2; there is no TP1 price to trail to.
    assert out["result"] == "OPEN"
    assert out["tp"] == 0



def test_full_exit_backtest_preserves_sparse_tp3_number():
    candles = [_tl(100.0, o=100.0, h=103.2, l=100.1, cl=103.0)]
    out = simulate_trade(
        entry=100.0,
        stop_loss=99.0,
        targets=[None, None, 103.0],
        future_candles=candles,
        direction="LONG",
    )

    assert out["result"] == "WIN"
    assert out["tp"] == 3



def test_runner_reports_performance_gate_and_long_short_breakdown():
    runner = BacktestRunner()
    for index in range(200):
        is_win = index % 4 != 0
        net_rr = 2.0 if is_win else -1.0
        runner._record({
            "_w": is_win,
            "net_rr": net_rr,
            "_levels": [],
            "direction": "LONG" if index % 2 == 0 else "SHORT",
        })

    stats = runner.statistics()
    assert stats["performance_gate"]["sample_sufficient"] is True
    assert stats["performance_gate"]["ready"] is True
    assert stats["direction_breakdown"]["LONG"]["total"] == 100
    assert stats["direction_breakdown"]["SHORT"]["total"] == 100


def test_runner_reports_raw_signal_and_decision_gate_counts():
    candles = _rising_series(500)

    def fake_analyze(window):
        if len(window["15m"]) == 401:
            return {
                "decision": {"action": "WAIT"},
                "signal": {"signal": "LONG"},
                "risk": {},
            }
        return None

    stats = BacktestRunner(analyze_fn=fake_analyze).run({"15m": candles})

    assert stats["analysis_calls"] == 200
    assert stats["empty_results"] == 199
    assert stats["raw_long_signals"] == 1
    assert stats["raw_short_signals"] == 0
    assert stats["non_directional_results"] == 0
    assert stats["action_counts"] == {"WAIT": 1}
    assert stats["candidate_signals"] == 0


def test_runner_reports_wait_reasons_and_mtf_alignment():
    candles = _rising_series(302)

    def fake_analyze(window):
        return {
            "decision": {"action": "WAIT"},
            "signal": {
                "signal": "WAIT",
                "wait_reason": "entry_not_confirmed",
                "signal_reason": "Entry not confirmed",
            },
            "analysis": {
                "mtf": {
                    "entry": "NONE",
                    "weekly": "BULLISH",
                    "daily": "NEUTRAL",
                    "h4": "BEARISH",
                }
            },
            "risk": {},
        }

    stats = BacktestRunner(analyze_fn=fake_analyze).run({"15m": candles})

    assert stats["analysis_calls"] == 2
    assert stats["wait_reason_counts"] == {"entry_not_confirmed": 2}
    assert stats["signal_reason_counts"] == {"Entry not confirmed": 2}
    assert stats["mtf_alignment_counts"] == {
        "entry=NONE|weekly=BULLISH|daily=NEUTRAL|h4=BEARISH": 2
    }


def test_limit_order_expires_after_configured_bars():
    runner = BacktestRunner(partial_exits=False, limit_expiry_bars=2)
    candles = [
        _candle(1, 100.0, 101.0, 98.0, 99.0),
        _candle(2, 99.0, 100.0, 96.0, 97.0),
        _candle(3, 97.0, 99.0, 96.0, 98.0),
    ]
    result = {
        "decision": {"action": "EXECUTE"},
        "signal": {"signal": "LONG"},
        "risk": {"entry": 95.0, "stop_loss": 90.0, "tp1": 105.0, "tp2": 110.0, "tp3": 115.0},
        "analysis": {"entry": {"entry_type": "LIMIT"}},
    }
    assert runner._to_trade(result, candles, entry_index=0) is None
    stats = runner.statistics()
    assert stats["expired_limits"] == 1
    assert stats["unfilled_limits"] == 1


def test_limit_order_is_cancelled_if_target_hits_before_fill(monkeypatch):
    monkeypatch.setattr(Config, "MINIMUM_NET_RR", 1.5, raising=False)
    runner = BacktestRunner(partial_exits=False, limit_expiry_bars=4)
    candles = [
        _candle(1, 99.0, 101.0, 96.0, 100.0),  # TP reached; limit 95 untouched
        _candle(2, 100.0, 101.0, 94.0, 95.0),
    ]
    result = {
        "decision": {"action": "EXECUTE"},
        "signal": {"signal": "LONG"},
        "risk": {"entry": 95.0, "stop_loss": 90.0, "tp1": 100.0, "tp2": 105.0, "tp3": 110.0},
        "analysis": {"entry": {"entry_type": "LIMIT"}},
    }
    assert runner._to_trade(result, candles, entry_index=0) is None
    assert runner.statistics()["stale_limit_targets_rebased"] == 1
    assert runner.statistics()["stale_limits_cancelled"] == 0
    assert runner.statistics()["stale_limit_target_before_fill"] == 1


def test_signal_candle_target_touch_is_counted_separately_for_stale_limit(monkeypatch):
    monkeypatch.setattr(Config, "MINIMUM_NET_RR", 1.5, raising=False)
    runner = BacktestRunner(partial_exits=False, limit_expiry_bars=4)
    candles = [
        _candle(1, 99.0, 101.0, 96.0, 99.0),
        _candle(2, 99.0, 100.0, 94.0, 95.0),
    ]
    result = {
        "decision": {"action": "EXECUTE"},
        "signal": {"signal": "LONG"},
        "risk": {"entry": 95.0, "stop_loss": 90.0, "tp1": 100.0, "tp2": 105.0, "tp3": 110.0},
        "analysis": {"entry": {"entry_type": "LIMIT"}},
    }
    assert runner._to_trade(result, candles, entry_index=1, signal_index=0) is None
    stats = runner.statistics()
    assert stats["stale_limit_targets_rebased"] == 1
    assert stats["stale_limits_cancelled"] == 0
    assert stats["stale_limit_signal_candle_target"] == 1
    assert stats["stale_limit_target_before_fill"] == 0


def test_trade_history_contains_actual_fill_and_plan_diagnostics():
    runner = BacktestRunner(partial_exits=False, limit_expiry_bars=4)
    candles = [
        _candle(1, 100.0, 100.0, 96.0, 99.0),  # not filled
        _candle(2, 99.0, 100.0, 94.0, 95.0),   # fills at 95 intrabar
        _candle(3, 95.0, 102.0, 94.0, 101.0),  # TP1
    ]
    result = {
        "decision": {"action": "EXECUTE"},
        "signal": {"signal": "LONG"},
        "risk": {"entry": 95.0, "stop_loss": 90.0, "tp1": 101.0, "tp2": 105.0, "tp3": 110.0},
        "analysis": {"entry": {"entry_type": "LIMIT"}},
    }
    trade = runner._to_trade(result, candles, entry_index=0, signal_index=0)
    assert trade is not None
    assert trade["planned_entry"] == 95.0
    assert trade["entry"] == 95.0
    assert trade["fill_delay_bars"] == 1
    assert trade["signal_time"] == 1
    assert trade["entry_time"] == 2
    assert trade["exit_reason"] == "TP1"


def test_partial_exit_reports_trailing_stop_not_last_tp_as_exit_reason():
    candles = [
        _tl(10.0, h=11.1, l=10.1, cl=10.6, t=1),
        _tl(10.5, h=10.6, l=9.9, cl=10.0, t=2),
    ]
    out = simulate_trade_partial(10.0, 9.0, [11.0, 12.0], candles, "LONG")
    assert out["exit_reason"] == "TRAILING_STOP"
    assert out["exit_offset"] == 1



def test_partial_exit_uses_50_30_20_weights_when_configured():
    candles = [
        _tl(100.0, o=100.0, h=101.2, l=100.1, cl=101.0, t=1),
        _tl(101.2, o=101.2, h=102.2, l=101.1, cl=102.0, t=2),
        _tl(102.2, o=102.2, h=103.2, l=102.1, cl=103.0, t=3),
    ]
    out = simulate_trade_partial(
        100.0, 99.0, [101.0, 102.0, 103.0], candles, "LONG",
        tp_weights={"tp1": 0.5, "tp2": 0.3, "tp3": 0.2},
    )
    assert out["result"] == "WIN"
    assert out["tp"] == 3
    assert out["net_rr"] == pytest.approx(1.7, abs=1e-4)


def test_partial_exit_gap_through_trailing_stop_uses_open_price():
    candles = [
        _tl(100.0, o=100.0, h=101.2, l=100.1, cl=101.0, t=1),
        _tl(99.0, o=99.0, h=100.0, l=98.5, cl=99.0, t=2),
    ]
    out = simulate_trade_partial(100.0, 99.0, [101.0, 102.0], candles, "LONG")
    assert out["result"] == "LOSS"
    assert out["tp"] == 1
    # 50% at +1R, remaining 50% stopped at the 99 open (-1R): net 0R.
    assert out["net_rr"] == pytest.approx(0.0, abs=1e-4)
    assert out["exit_reason"] == "TRAILING_STOP"


def test_runner_reports_stage_rejection_diagnostics():
    candles = _rising_series(500)

    def fake_analyze(window):
        if len(window["15m"]) != 400:
            return None
        return {
            "decision": {
                "action": "WAIT",
                "critical_blockers": ["Entry invalid", "RR below minimum"],
            },
            "signal": {"signal": "WAIT", "wait_reason": "Entry not confirmed"},
            "risk": {},
            "analysis": {
                "mtf": {
                    "entry": "NONE",
                    "entry_source": "NONE",
                    "weekly": "NEUTRAL",
                    "daily": "BEARISH",
                    "h4": "NEUTRAL",
                },
                "liquidity_sweep": {
                    "is_sweep": True,
                    "sweep_side": "SELL_SIDE",
                    "post_structure": {"confirmed": False},
                },
                "confirmation": {
                    "confirmed": False,
                    "reason": "15m directional BOS/CHoCH missing",
                },
                "entry": {"valid": False, "reason": "No MTF direction"},
            },
        }

    stats = BacktestRunner(analyze_fn=fake_analyze).run({"15m": candles})
    assert stats["mtf_entry_source_counts"] == {"NONE": 1}
    assert stats["liquidity_sweep_state_counts"] == {
        "sweep=True|confirmed=False|side=SELL_SIDE": 1
    }
    assert stats["confirmation_reason_counts"] == {
        "15m directional BOS/CHoCH missing": 1
    }
    assert stats["entry_validity_counts"] == {"INVALID": 1}
    assert stats["decision_blocker_counts"] == {
        "Entry invalid": 1,
        "RR below minimum": 1,
    }


def test_limit_is_cancelled_when_target_was_hit_on_signal_candle(monkeypatch):
    monkeypatch.setattr(Config, "MINIMUM_NET_RR", 1.5, raising=False)
    runner = BacktestRunner(partial_exits=False, limit_expiry_bars=4)
    candles = [
        _candle(1, 99.0, 101.0, 96.0, 99.5),  # TP1 hit before order submission
        _candle(2, 99.5, 100.0, 94.0, 95.0),   # later touches the pending limit
    ]
    result = {
        "decision": {"action": "EXECUTE"},
        "signal": {"signal": "LONG"},
        "risk": {"entry": 95.0, "stop_loss": 90.0, "tp1": 100.0, "tp2": 105.0, "tp3": 110.0},
        "analysis": {"entry": {"entry_type": "LIMIT"}},
    }
    assert runner._to_trade(result, candles, entry_index=1, signal_index=0) is None
    assert runner.statistics()["stale_limit_targets_rebased"] == 1
    assert runner.statistics()["stale_limits_cancelled"] == 0
    assert runner.statistics()["candidate_signals"] == 1


def test_missed_limit_reassesses_market_at_next_open_when_net_rr_is_valid():
    runner = BacktestRunner(partial_exits=False, fee_rate=0.0)
    candles = [
        _candle(1, 100.0, 100.5, 99.5, 100.0),
        # LIMIT=99 is not touched; TP1=102 is reached later in this candle.
        # A MARKET entry at open=100 still has 2R to TP1 and is valid.
        _candle(2, 100.0, 102.5, 99.9, 102.0),
        _candle(3, 102.0, 103.5, 101.5, 103.0),
    ]
    result = {
        "decision": {"action": "EXECUTE"},
        "signal": {"signal": "LONG"},
        "risk": {"entry": 99.8, "stop_loss": 99.0, "tp1": 102.0, "tp2": 103.0, "tp3": 104.0},
        "analysis": {"entry": {"entry_type": "LIMIT"}},
    }
    trade = runner._to_trade(result, candles, entry_index=1, signal_index=0)
    assert trade is not None
    assert trade["entry_type"] == "MARKET_FALLBACK"
    assert trade["entry"] == 100.0
    assert runner.market_fallback_fills == 1
    assert runner.stale_limits_cancelled == 0


def test_missed_limit_market_reassessment_rejected_when_net_rr_below_minimum():
    runner = BacktestRunner(partial_exits=False, fee_rate=0.002)
    candles = [
        _candle(1, 100.0, 100.5, 99.5, 100.0),
        # Open=101 leaves only 1R to TP1=102, below the 1.50R floor.
        _candle(2, 101.0, 102.5, 100.95, 102.0),
        _candle(3, 102.0, 103.0, 101.5, 102.5),
    ]
    result = {
        "decision": {"action": "EXECUTE"},
        "signal": {"signal": "LONG"},
        "risk": {"entry": 100.9, "stop_loss": 98.0, "tp1": 102.0, "tp2": 103.0, "tp3": 104.0},
        "analysis": {"entry": {"entry_type": "LIMIT"}},
    }
    assert runner._to_trade(result, candles, entry_index=1, signal_index=0) is None
    assert runner.market_fallback_fills == 0
    assert runner.market_fallback_rejected_rr == 1
    assert runner.stale_limits_cancelled == 1


def test_runner_rebases_already_touched_tp_to_remaining_structural_target_before_limit_fill():
    runner = BacktestRunner(
        partial_exits=False, fee_rate=0.0002, limit_expiry_bars=5
    )
    candles = [
        _candle(1, 101.0, 102.5, 100.2, 102.2),  # TP1 touched before order exists
        _candle(2, 102.2, 103.0, 100.5, 102.8),  # TP1 still passed; no fill
        _candle(3, 102.8, 104.5, 100.5, 104.0),  # TP2 touched; no fill
        _candle(4, 104.0, 105.0, 99.5, 100.5),   # LIMIT fills; TP3 remains
        _candle(5, 100.5, 107.0, 100.0, 106.5),  # remaining TP3
    ]
    result = {
        "decision": {"action": "EXECUTE"},
        "signal": {"signal": "LONG"},
        "risk": {"entry": 100.0, "stop_loss": 99.0, "tp1": 102.0, "tp2": 104.0, "tp3": 106.0},
        "analysis": {"entry": {"entry_type": "LIMIT", "poi_source": "FVG", "poi_zone": {"low": 99.5, "high": 100.5}}},
    }
    trade = runner._to_trade(result, candles, entry_index=1, signal_index=0)
    assert trade is not None
    assert trade["entry"] == 100.0
    assert trade["tps"] == [106.0, None, None]
    assert runner.stale_limit_targets_rebased >= 2
    assert trade["result"] == "WIN"


def test_runner_rebases_already_touched_tp_for_short_limit_before_fill():
    runner = BacktestRunner(
        partial_exits=False, fee_rate=0.0002, limit_expiry_bars=5
    )
    candles = [
        _candle(1, 100.0, 100.5, 97.5, 97.8),  # TP1 touched before order exists
        _candle(2, 97.8, 99.5, 97.0, 97.2),    # no fill; TP2 remains ahead
        _candle(3, 97.2, 99.0, 95.5, 96.0),    # TP2 touched; TP3 remains
        _candle(4, 96.0, 100.5, 95.0, 100.2),  # short LIMIT fills
        _candle(5, 100.2, 100.5, 93.5, 94.0),  # remaining TP3
    ]
    result = {
        "decision": {"action": "EXECUTE"},
        "signal": {"signal": "SHORT"},
        "risk": {"entry": 100.0, "stop_loss": 101.0, "tp1": 98.0, "tp2": 96.0, "tp3": 94.0},
        "analysis": {"entry": {"entry_type": "LIMIT", "poi_source": "FVG", "poi_zone": {"low": 99.5, "high": 100.5}}},
    }
    trade = runner._to_trade(result, candles, entry_index=1, signal_index=0)
    assert trade is not None
    assert trade["entry"] == 100.0
    assert trade["tps"] == [94.0, None, None]
    assert runner.stale_limit_targets_rebased >= 2
    assert trade["result"] == "WIN"


def test_runner_reports_long_short_fill_rates_separately():
    runner = BacktestRunner()
    runner.candidate_direction_counts = {"LONG": 4, "SHORT": 6}
    runner.filled_direction_counts = {"LONG": 2, "SHORT": 1}
    rates = runner.statistics()["direction_fill_rates"]
    assert rates == {"LONG": 50.0, "SHORT": 16.67}


def test_runner_deduplicates_the_same_structural_setup_across_candles():
    result = {
        "decision": {"action": "EXECUTE"},
        "signal": {"signal": "LONG"},
        "risk": {"entry": 90.0, "stop_loss": 89.0, "tp1": 95.0, "tp2": 96.0, "tp3": 97.0},
        "analysis": {"entry": {
            "entry_type": "LIMIT", "direction": "LONG",
            "setup_candidate_id": "LONG:FVG:0", "poi_source": "FVG",
            "poi_zone": {"low": 90.0, "high": 91.0},
        }},
    }
    runner = BacktestRunner(analyze_fn=lambda window: result, limit_expiry_bars=2)
    candles = [_candle(i, 100.0, 101.0, 99.0, 100.0) for i in range(310)]
    stats = runner.run({"symbol": "BTC/USDT:USDT", "15m": candles})
    assert stats["candidate_signals"] == 1
    assert stats["duplicate_setups_skipped"] > 0


def test_backtest_does_not_count_overlapping_positions_as_independent_trades():
    runner = BacktestRunner(
        analyze_fn=lambda window: {
            "decision": {"action": "EXECUTE"},
            "signal": {"signal": "LONG"},
            "risk": {
                "entry": 100.0, "stop_loss": 99.0,
                "tp1": 102.0, "tp2": 103.0, "tp3": 104.0,
            },
            "analysis": {"entry": {"entry_type": "MARKET"}},
        },
        fee_rate=0.0,
        partial_exits=False,
    )
    candles = [_candle(i, 100.0, 103.0, 99.5, 102.0) for i in range(306)]
    stats = runner.run({"symbol": "BTC/USDT:USDT", "15m": candles}, step=1)
    assert stats["total"] >= 2
    assert stats["overlapping_signals_skipped"] >= 1
    entries = [trade["entry_index"] for trade in stats["trade_history"]]
    exits = [trade["exit_index"] for trade in stats["trade_history"]]
    assert all(entries[i + 1] > exits[i] for i in range(len(entries) - 1))



def test_full_exit_simulator_accounts_for_long_stop_gap_at_open():
    candles = [_candle(1, 80.0, 82.0, 79.0, 81.0)]
    out = simulate_trade(100.0, 90.0, [110.0, 120.0], candles, "LONG")
    assert out["result"] == "LOSS"
    assert out["exit_price"] == 80.0
    assert out["stop_gap"] is True
    assert out["stop_gap_distance"] == 10.0
    assert out["stop_gap_r"] == 1.0
    assert out["net_rr"] == -2.0


def test_partial_simulator_accounts_for_short_stop_gap_at_open():
    candles = [_candle(1, 108.0, 109.0, 107.0, 108.5)]
    out = simulate_trade_partial(100.0, 101.0, [99.0, 98.0, 97.0], candles, "SHORT")
    assert out["result"] == "LOSS"
    assert out["exit_price"] == 108.0
    assert out["stop_gap"] is True
    assert out["stop_gap_distance"] == 7.0
    assert out["stop_gap_r"] == 7.0
    assert out["net_rr"] == -8.0


def test_mtf_trade_breakdown_separates_direction_and_context():
    runner = BacktestRunner()
    runner._record({
        "_w": False, "net_rr": -1.0, "_levels": [], "direction": "LONG",
        "mtf_context": {"weekly": "BEARISH", "daily": "BEARISH", "h4": "BULLISH"},
    })
    runner._record({
        "_w": True, "net_rr": 1.5, "_levels": [3], "direction": "SHORT",
        "mtf_context": {"weekly": "BEARISH", "daily": "BEARISH", "h4": "BEARISH"},
    })
    stats = runner.statistics()
    assert stats["mtf_trade_breakdown"]["LONG|weekly=BEARISH|daily=BEARISH|h4=BULLISH"]["losses"] == 1
    assert stats["mtf_trade_breakdown"]["SHORT|weekly=BEARISH|daily=BEARISH|h4=BEARISH"]["wins"] == 1



def test_runner_step_one_analyzes_every_closed_15m_candle():
    candles = _rising_series(305)
    analyzed = []

    def fake_analyze(window):
        analyzed.append(len(window["15m"]))
        return None

    stats = BacktestRunner(analyze_fn=fake_analyze).run({"15m": candles}, step=1)

    assert stats["analysis_calls"] == 5
    assert analyzed == [301, 302, 303, 304, 305]


def test_runner_step_five_is_explicitly_less_frequent():
    candles = _rising_series(305)
    analyzed = []

    def fake_analyze(window):
        analyzed.append(len(window["15m"]))
        return None

    stats = BacktestRunner(analyze_fn=fake_analyze).run({"15m": candles}, step=5)

    assert stats["analysis_calls"] == 1
    assert analyzed == [301]


def test_partial_backtest_applies_round_trip_fee_exactly_once():
    runner = BacktestRunner(fee_rate=0.002, partial_exits=True)
    candles = [_candle(1, 100.0, 101.5, 100.1, 101.0)]
    result = {
        "decision": {"action": "EXECUTE"},
        "signal": {"signal": "LONG"},
        "risk": {"entry": 100.0, "stop_loss": 99.0, "tp1": 101.0, "tp2": None, "tp3": None},
    }

    trade = runner._to_trade(result, candles, entry_index=0)

    # One fully closed partial tranche: gross +1R, one round-trip fee = -0.2R.
    assert trade is not None
    assert trade["net_rr"] == 0.8


def test_partial_backtest_stop_loss_includes_round_trip_fee_once():
    runner = BacktestRunner(fee_rate=0.002, partial_exits=True)
    candles = [_candle(1, 100.0, 100.5, 98.5, 99.0)]
    result = {
        "decision": {"action": "EXECUTE"},
        "signal": {"signal": "LONG"},
        "risk": {"entry": 100.0, "stop_loss": 99.0, "tp1": 101.0, "tp2": None, "tp3": None},
    }

    trade = runner._to_trade(result, candles, entry_index=0)

    assert trade is not None
    assert trade["net_rr"] == -1.2


def test_runner_applies_fee_spread_and_slippage_costs_once():
    runner = BacktestRunner(
        fee_rate=0.002,
        spread_rate=0.0002,
        slippage_rate=0.0003,
        partial_exits=False,
    )
    candles = [_candle(1, 100.0, 101.5, 100.1, 101.0)]
    result = {
        "decision": {"action": "EXECUTE"},
        "signal": {"signal": "LONG"},
        "risk": {"entry": 100.0, "stop_loss": 99.0, "tp1": 101.0, "tp2": None, "tp3": None},
    }

    trade = runner._to_trade(result, candles, entry_index=0)

    assert trade is not None
    assert trade["fee_rr"] == 0.2
    assert trade["spread_slippage_rr"] == 0.05
    assert trade["execution_cost_rr"] == 0.25
    assert trade["net_rr"] == 0.75
    assert trade["cost_model"] == "round_trip_fee_plus_spread_slippage_proxy"



def test_runner_separates_gross_stop_r_from_execution_costs():
    candles = [
        _candle(1, 100.0, 100.2, 99.8, 100.0),
        _candle(2, 100.0, 101.2, 99.9, 101.0),
        _candle(3, 100.0, 100.2, 99.8, 100.0),
    ]
    runner = BacktestRunner(fee_rate=0.002, spread_rate=0.0002, slippage_rate=0.0003)
    result = {
        "decision": {"action": "EXECUTE"},
        "signal": {"signal": "SHORT"},
        "risk": {"entry": 100.0, "stop_loss": 100.5, "tp1": 99.0, "tp2": 98.0, "tp3": 97.0},
        "analysis": {"entry": {"entry_type": "LIMIT"}, "mtf": {}},
    }

    trade = runner._to_trade(result, candles, 1, signal_index=0)

    assert trade is not None
    assert trade["gross_rr"] == -1.0
    assert trade["execution_cost_rr"] == 0.5
    assert trade["net_rr"] == -1.5


def test_statistics_separate_gross_and_net_pf_and_direction_metrics():
    runner = BacktestRunner()
    runner._record({
        "_w": False, "gross_rr": -1.0, "net_rr": -1.5,
        "execution_cost_rr": 0.5, "_levels": [], "direction": "SHORT",
    })
    runner._record({
        "_w": True, "gross_rr": 2.0, "net_rr": 1.5,
        "execution_cost_rr": 0.5, "_levels": [], "direction": "LONG",
    })

    stats = runner.statistics()
    assert stats["gross_rr"] == 1.0
    assert stats["gross_expectancy"] == 0.5
    assert stats["gross_profit_factor"] == 2.0
    assert stats["net_rr"] == 0.0
    assert stats["profit_factor"] == 1.0
    assert stats["total_execution_cost_rr"] == 1.0
    assert stats["direction_breakdown"]["LONG"]["gross_rr"] == 2.0
    assert stats["direction_breakdown"]["LONG"]["net_rr"] == 1.5
    assert stats["direction_breakdown"]["SHORT"]["gross_rr"] == -1.0
    assert stats["direction_breakdown"]["SHORT"]["net_rr"] == -1.5



def test_backtest_tracks_directional_decisions_and_blockers():
    candles = _rising_series(302)

    def fake_analyze(window):
        return {
            "decision": {
                "action": "SKIP",
                "critical_blockers": ["net_rr_below_minimum"],
            },
            "signal": {"signal": "LONG"},
            "analysis": {"mtf": {"entry": "LONG", "weekly": "NEUTRAL", "daily": "BEARISH", "h4": "BULLISH"}},
            "risk": {},
        }

    stats = BacktestRunner(analyze_fn=fake_analyze).run({"15m": candles})
    assert stats["direction_action_counts"] == {"LONG|SKIP": 2}
    assert stats["direction_blocker_counts"] == {"LONG|net_rr_below_minimum": 2}


def test_runner_respects_unified_decision_entry_and_risk_validity():
    runner = BacktestRunner(partial_exits=False)
    candles = [_candle(1, 100.0, 101.0, 99.5, 100.5)]
    result = {
        "decision": {"action": "EXECUTE", "entry_valid": False, "risk_valid": True},
        "signal": {"signal": "LONG"},
        "risk": {"side": "LONG", "entry": 100.0, "stop_loss": 99.0, "tp1": 102.0},
        "analysis": {"entry": {"entry_type": "MARKET"}},
    }
    assert runner._to_trade(result, candles, entry_index=0) is None
    assert runner.invalid_candidates == 1


def test_runner_rejects_risk_payload_with_opposite_direction():
    runner = BacktestRunner(partial_exits=False)
    candles = [_candle(1, 100.0, 101.0, 99.5, 100.5)]
    result = {
        "decision": {"action": "EXECUTE"},
        "signal": {"signal": "LONG"},
        "risk": {"side": "SHORT", "entry": 100.0, "stop_loss": 101.0, "tp1": 98.0},
        "analysis": {"entry": {"entry_type": "MARKET"}},
    }
    assert runner._to_trade(result, candles, entry_index=0) is None
    assert runner.invalid_candidates == 1


def test_limit_gap_fill_is_accounted_as_marketable_taker():
    runner = BacktestRunner(partial_exits=False)
    candles = [
        _candle(1, 94.0, 96.0, 93.0, 95.0),  # Opens through 95 buy limit.
        _candle(2, 95.0, 102.0, 94.5, 101.0),  # TP1.
    ]
    result = {
        "decision": {"action": "EXECUTE"},
        "signal": {"signal": "LONG"},
        "risk": {"entry": 95.0, "stop_loss": 90.0, "tp1": 101.0, "tp2": 105.0, "tp3": 110.0},
        "analysis": {"entry": {"entry_type": "LIMIT"}},
    }
    trade = runner._to_trade(result, candles, entry_index=0)
    assert trade is not None
    assert trade["entry_type"] == "MARKETABLE_LIMIT"
    assert trade["entry"] == pytest.approx(94.0)
    assert trade["execution_cost_rr"] > 0


def test_stop_atr_diagnostics_use_final_risk_distance():
    candles = _rising_series(302)

    def fake_analyze(window):
        return {
            "decision": {"action": "WAIT"},
            "signal": {"signal": "WAIT"},
            "risk": {"atr": 1.0, "risk": 0.8, "requested_risk": 0.2},
        }

    stats = BacktestRunner(analyze_fn=fake_analyze).run({"15m": candles})
    assert stats["stop_atr_buckets"] == {">=0.50 ATR": 2}


def test_runner_deducts_adverse_historical_funding_from_net_r():
    runner = BacktestRunner(
        fee_rate=0.0, partial_exits=False, spread_rate=0.0, slippage_rate=0.0
    )
    candles = [_candle(0, 100.0, 102.0, 100.1, 101.5)]
    result = {
        "decision": {"action": "EXECUTE"},
        "signal": {"signal": "LONG"},
        "risk": {"entry": 100.0, "stop_loss": 99.0, "tp1": 101.5, "tp2": None, "tp3": None},
        "analysis": {"entry": {"entry_type": "MARKET"}},
    }
    trade = runner._to_trade(
        result, candles, entry_index=0,
        funding_records=[{"timestamp": 900_000, "value": 0.001}],
    )
    assert trade is not None
    assert trade["gross_rr"] == 1.5
    assert trade["funding_cost_r"] == 0.1015
    assert trade["net_rr"] == 1.3985
    runner._record(trade)
    stats = runner.statistics()
    assert stats["total_funding_cost_r"] == 0.1015
    assert stats["funding_events_charged"] == 1


def test_runner_exposes_only_asof_funding_records_to_analysis():
    candles = [_candle(i * 900_000, 100.0, 100.2, 99.8, 100.0) for i in range(302)]
    captured = []
    decision_ms = candles[300].time + 900_000

    def fake_analyze(window):
        if len(window["15m"]) == 301:
            captured.extend(window["funding_records"])
        return None

    runner = BacktestRunner(analyze_fn=fake_analyze)
    stats = runner.run({
        "symbol": "BTC/USDT:USDT",
        "15m": candles,
        "funding_records": [
            {"timestamp": decision_ms, "value": 0.001},
            {"timestamp": decision_ms + 900_000, "value": 0.002},
        ],
        "derivatives_data_quality": {"funding": "HISTORICAL"},
    })
    assert captured == [{"timestamp": decision_ms, "value": 0.001}]
    assert stats["funding_data_quality"]["funding"] == "HISTORICAL"
    assert stats["microstructure_data_quality"]["analysis_samples"] == 2
    assert stats["microstructure_data_quality"]["archived_snapshots"] == 0


def test_smc_replay_uses_same_max_holding_time_exit_as_strategy_replay():
    runner = BacktestRunner(
        maker_fee_rate=0.0, taker_fee_rate=0.0, spread_rate=0.0, slippage_rate=0.0,
        tp_weights={"tp1": 0.5, "tp2": 0.3, "tp3": 0.2}, max_holding_bars=2,
    )
    candles = [
        _candle(0, 100.0, 101.0, 99.0, 101.0),
        _candle(900_000, 101.0, 101.5, 100.5, 101.0),
    ]
    result = {
        "decision": {"action": "EXECUTE"},
        "signal": {"signal": "LONG"},
        "risk": {"entry": 100.0, "stop_loss": 98.0, "tp1": 110.0, "tp2": 120.0, "tp3": 130.0},
        "analysis": {"entry": {"entry_type": "MARKET"}},
    }
    trade = runner._to_trade(result, candles, entry_index=0)
    assert trade is not None
    assert trade["exit_reason"] == "TIME_EXIT"
    assert trade["gross_rr"] == 0.5
    assert trade["net_rr"] == 0.5
