from motor_ablation import DisabledMotor, _compare, _snapshot_for_index


class _Candle:
    def __init__(self, time, close):
        self.time = time
        self.close = close


def test_ablation_snapshot_uses_only_closed_higher_timeframe_candles():
    history = {
        "15m": [_Candle(0, 100), _Candle(900_000, 101)],
        "1h": [_Candle(-3_600_000, 99), _Candle(0, 100)],
        "4h": [_Candle(-14_400_000, 98), _Candle(0, 100)],
        "1d": [_Candle(-86_400_000, 97), _Candle(0, 100)],
        "1w": [_Candle(-604_800_000, 96), _Candle(0, 100)],
    }
    snapshot = _snapshot_for_index(history, 0, "BTC/USDT:USDT")
    assert len(snapshot["15m"]) == 1
    assert [item.time for item in snapshot["1h"]] == [-3_600_000]
    assert [item.time for item in snapshot["4h"]] == [-14_400_000]
    assert [item.time for item in snapshot["1d"]] == [-86_400_000]
    assert [item.time for item in snapshot["1w"]] == [-604_800_000]
    assert snapshot["current_price"] == 100


def test_disabled_motor_is_a_safe_noop_target():
    motor = DisabledMotor()
    assert motor.analyze({"symbol": "BTC/USDT"}) is None
    assert motor.MARKET_MAX_SPREAD_PCT == 0


def test_ablation_comparison_distinguishes_decision_and_geometry_changes():
    baseline = {"action": "EXECUTE", "signal": "LONG", "direction": "LONG", "entry": 100.0, "stop_loss": 98.0}
    unchanged = dict(baseline)
    changed = {**baseline, "action": "SKIP", "entry": 101.0}
    assert _compare(baseline, unchanged) == {
        "decision_changed": False, "plan_changed": False, "changed_fields": []
    }
    comparison = _compare(baseline, changed)
    assert comparison["decision_changed"] is True
    assert comparison["plan_changed"] is True
    assert comparison["changed_fields"] == ["action", "entry"]
