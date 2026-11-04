import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest_runner import BacktestRunner


def _candle(index):
    from core.candle import Candle
    base = 100.0 + index * 0.01
    return Candle(
        time=index * 15 * 60 * 1000,
        open=base,
        high=base + 0.1,
        low=base - 0.1,
        close=base + 0.02,
        volume=100.0,
    )


def test_runner_reports_entry_stop_target_and_order_diagnostics():
    candles = [_candle(index) for index in range(302)]

    def fake_analyze(window):
        return {
            "decision": {"action": "WAIT"},
            "signal": {"signal": "WAIT", "wait_reason": "Entry invalid"},
            "analysis": {
                "mtf": {"entry": "SHORT", "weekly": "BEARISH", "daily": "BEARISH", "h4": "BEARISH"},
                "entry": {
                    "valid": False,
                    "reason": "Weak setup",
                    "entry_reason_code": "ENTRY_SCORE_BELOW_MINIMUM",
                    "entry_type": "LIMIT",
                },
                "dynamic_tp": {"reason": "no_valid_structural_targets", "missing_rr_level": 2.0},
            },
            "risk": {"risk_setup_valid": False, "reason_code": "UNSAFE_WIDE_OR_EXPAND_DISABLED", "atr": 100.0, "requested_risk": 15.0},
        }

    stats = BacktestRunner(analyze_fn=fake_analyze).run({"15m": candles})

    assert stats["entry_reason_counts"] == {"ENTRY_SCORE_BELOW_MINIMUM": 2}
    assert stats["entry_type_counts"] == {"LIMIT": 2}
    assert stats["risk_reason_counts"] == {"UNSAFE_WIDE_OR_EXPAND_DISABLED": 2}
    assert stats["target_reason_counts"] == {"no_valid_structural_targets": 2}
    assert stats["target_missing_rr_counts"] == {"2R": 2}
    assert stats["stop_atr_buckets"] == {"<0.25 ATR": 2}
