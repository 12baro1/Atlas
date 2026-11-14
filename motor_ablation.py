"""Replay-based specialist motor ablation for deterministic Atlas snapshots.

This measures decision sensitivity to removing one motor at a time. It is not
a substitute for outcome-based PnL attribution or an OOS profitability test.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os

ABLATION_EXCLUDED = {"decision", "risk", "rr", "dynamic_tp", "news_filter", "correlation", "cooldown", "learning"}


class DisabledMotor:
    """Safe null target used only by the offline ablation runner."""

    def __getattr__(self, name):
        if name.isupper():
            return 0
        return lambda *args, **kwargs: None


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _snapshot_for_index(history, index, symbol, derivatives=None, microstructure=None):
    """Build an as-of snapshot using only candles closed by the decision time."""
    from backtest import TIMEFRAME_DURATION_MS
    candles_15m = history.get("15m") or []
    if index < 0 or index >= len(candles_15m):
        raise IndexError("15m sample index is outside loaded history")
    signal_candle = candles_15m[index]
    decision_ms = int(signal_candle.time) + TIMEFRAME_DURATION_MS["15m"]
    snapshot = {
        "symbol": symbol, "15m": list(candles_15m[:index + 1]),
        "current_price": float(signal_candle.close),
        "current_price_timestamp_ms": decision_ms,
        "current_price_source": "BACKTEST_CLOSED_15M_CLOSE",
        "snapshot_timestamp_ms": decision_ms,
    }
    for timeframe in ("1h", "4h", "1d", "1w"):
        duration = TIMEFRAME_DURATION_MS[timeframe]
        snapshot[timeframe] = [
            candle for candle in (history.get(timeframe) or [])
            if int(candle.time) + duration <= decision_ms
        ]
    derivatives = derivatives or {}
    oi_rows = [row for row in derivatives.get("open_interest_records", []) if int(row.get("timestamp") or 0) <= decision_ms]
    funding_rows = [row for row in derivatives.get("funding_records", []) if int(row.get("timestamp") or 0) <= decision_ms]
    snapshot["open_interest"] = [row["value"] for row in oi_rows]
    snapshot["open_interest_timestamps_ms"] = [row["timestamp"] for row in oi_rows]
    snapshot["funding_rate"] = [row["value"] for row in funding_rows]
    snapshot["funding_rate_timestamps_ms"] = [row["timestamp"] for row in funding_rows]
    snapshot["derivatives_data_quality"] = derivatives.get("derivatives_data_quality", {})
    microstructure = microstructure or {}
    snapshot["orderbook"] = microstructure.get("orderbook")
    snapshot["orderbook_timestamp_ms"] = microstructure.get("orderbook_timestamp_ms")
    snapshot["recent_trades"] = microstructure.get("recent_trades")
    snapshot["recent_trades_timestamp_ms"] = microstructure.get("recent_trades_timestamp_ms")
    snapshot["microstructure_snapshot_timestamp_ms"] = microstructure.get("microstructure_snapshot_timestamp_ms")
    return snapshot


def _signature(result):
    result = result if isinstance(result, dict) else {}
    decision = result.get("decision") or {}
    signal = result.get("signal") or {}
    analysis = result.get("analysis") or {}
    entry = analysis.get("entry") or {}
    risk = result.get("risk") or {}
    return {
        "action": decision.get("action"), "signal": signal.get("signal"),
        "direction": entry.get("direction"), "entry_type": entry.get("entry_type"),
        "entry": _finite(risk.get("entry")), "stop_loss": _finite(risk.get("stop_loss")),
        "tp1": _finite(risk.get("tp1")), "tp2": _finite(risk.get("tp2")),
        "tp3": _finite(risk.get("tp3")),
        "weighted_net_rr": _finite(risk.get("weighted_net_rr") or risk.get("net_rr")),
    }


def _compare(baseline, ablated):
    decision_keys = ("action", "signal", "direction")
    plan_keys = ("entry_type", "entry", "stop_loss", "tp1", "tp2", "tp3", "weighted_net_rr")
    decision_changed = any(baseline.get(key) != ablated.get(key) for key in decision_keys)
    plan_changed = any(baseline.get(key) != ablated.get(key) for key in plan_keys)
    return {
        "decision_changed": decision_changed, "plan_changed": plan_changed,
        "changed_fields": [key for key in decision_keys + plan_keys if baseline.get(key) != ablated.get(key)],
    }


def run_ablation(symbol, days=14, samples=3, step=96, motors=None, output_path=None, include_derivatives=True):
    """Run baseline and one-motor-at-a-time ablations over identical historical snapshots."""
    from backtest import _disable_backtest_live_features, load_historical
    from engine import AtlasEngine
    from historical_derivatives import load_historical_derivatives
    from microstructure_archive import snapshot_at

    if int(days) <= 0 or int(samples) <= 0 or int(step) <= 0:
        raise ValueError("days, samples and step must be positive")
    _disable_backtest_live_features()
    history = load_historical(symbol, days=days)
    bars = history.get("15m") or []
    if len(bars) < 300:
        raise RuntimeError(f"Insufficient 15m history for ablation: {len(bars)} candles")
    last_index = len(bars) - 1
    indices = [last_index - step * offset for offset in reversed(range(samples))]
    indices = [index for index in indices if index >= 299]
    if not indices:
        raise RuntimeError("No valid post-warmup sample indices")
    start_ms = int(bars[indices[0]].time)
    end_ms = int(bars[indices[-1]].time) + 15 * 60 * 1000
    derivatives = load_historical_derivatives(symbol, start_ms, end_ms) if include_derivatives else {}
    engine = AtlasEngine()
    available = sorted(name for name in engine.main_engine.motors if name not in ABLATION_EXCLUDED)
    selected_motors = sorted(set(motors or available))
    unknown = sorted(set(selected_motors) - set(engine.main_engine.motors))
    if unknown:
        raise ValueError("Unknown motor names: " + ", ".join(unknown))
    rows = []
    for index in indices:
        candle = bars[index]
        decision_ms = int(candle.time) + 15 * 60 * 1000
        micro = snapshot_at(symbol, decision_ms) or {}
        snapshot = _snapshot_for_index(history, index, symbol, derivatives, micro)
        baseline_result = engine.analyze(copy.deepcopy(snapshot))
        baseline = _signature(baseline_result)
        baseline_attribution = ((baseline_result.get("main_engine") or {}).get("motor_attribution") or {})
        sample = {"decision_time_ms": decision_ms, "baseline": baseline, "motor_results": {}}
        for motor_name in selected_motors:
            original_target = engine.main_engine._targets[motor_name]
            try:
                setattr(engine, motor_name, DisabledMotor())
                ablated_result = engine.analyze(copy.deepcopy(snapshot))
                ablated = _signature(ablated_result)
                comparison = _compare(baseline, ablated)
                attribution = baseline_attribution.get("motors", {}).get(motor_name, {})
                sample["motor_results"][motor_name] = {
                    "status": "COMPLETED", **comparison,
                    "baseline_event_ids": attribution.get("event_ids", []),
                    "consumed_event_ids": attribution.get("consumed_event_ids", []),
                    "ablated": ablated,
                }
            except Exception as exc:
                sample["motor_results"][motor_name] = {
                    "status": "ERROR", "error": f"{type(exc).__name__}: {exc}",
                    "baseline_event_ids": (baseline_attribution.get("motors", {}).get(motor_name) or {}).get("event_ids", []),
                }
            finally:
                setattr(engine, motor_name, original_target)
        rows.append(sample)
    summary = {}
    for motor_name in selected_motors:
        outcomes = [sample["motor_results"].get(motor_name, {}) for sample in rows]
        completed = [item for item in outcomes if item.get("status") == "COMPLETED"]
        summary[motor_name] = {
            "samples": len(outcomes), "completed": len(completed),
            "errors": len(outcomes) - len(completed),
            "decision_changed": sum(bool(item.get("decision_changed")) for item in completed),
            "plan_changed": sum(bool(item.get("plan_changed")) for item in completed),
            "consumed_event_ids": sorted({event_id for item in outcomes for event_id in item.get("consumed_event_ids", [])}),
        }
    report = {
        "schema_version": 1, "symbol": symbol, "days": int(days),
        "samples": len(rows), "sample_step_bars": int(step),
        "decision_time_basis": "closed 15m candle close; closed HTF candles only",
        "data_quality": derivatives.get("derivatives_data_quality", {}) if include_derivatives else {"derivatives": "DISABLED"},
        "interpretation": "Ablation measures decision/plan sensitivity on these snapshots only; it does not prove causal PnL contribution or profitability.",
        "motor_summary": summary, "sample_results": rows,
    }
    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2, default=str)
    return report


def main():
    parser = argparse.ArgumentParser(description="Atlas specialist motor ablation replay")
    parser.add_argument("--symbol", default="BTC/USDT:USDT")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--step", type=int, default=96, help="Bars between sampled decisions (96 = 1 day)")
    parser.add_argument("--motors", help="Comma-separated motor names; default: all ablatable specialist motors")
    parser.add_argument("--output", default="reports/motor_ablation.json")
    parser.add_argument("--no-derivatives", action="store_true")
    args = parser.parse_args()
    motors = [item.strip() for item in args.motors.split(",") if item.strip()] if args.motors else None
    report = run_ablation(args.symbol, days=args.days, samples=args.samples, step=args.step,
                          motors=motors, output_path=args.output, include_derivatives=not args.no_derivatives)
    print(f"Motor ablation | {report[chr(115)+chr(121)+chr(109)+chr(98)+chr(111)+chr(108)]} | {report[chr(115)+chr(97)+chr(109)+chr(112)+chr(108)+chr(101)+chr(115)]} samples")
    for name, metrics in sorted(report["motor_summary"].items()):
        print(f"{name:24} decision={metrics[chr(100)+chr(101)+chr(99)+chr(105)+chr(115)+chr(105)+chr(111)+chr(110)+chr(95)+chr(99)+chr(104)+chr(97)+chr(110)+chr(103)+chr(101)+chr(100)]}/{metrics[chr(99)+chr(111)+chr(109)+chr(112)+chr(108)+chr(101)+chr(116)+chr(101)+chr(100)]}  plan={metrics[chr(112)+chr(108)+chr(97)+chr(110)+chr(95)+chr(99)+chr(104)+chr(97)+chr(110)+chr(103)+chr(101)+chr(100)]}/{metrics[chr(99)+chr(111)+chr(109)+chr(112)+chr(108)+chr(101)+chr(116)+chr(101)+chr(100)]}  errors={metrics[chr(101)+chr(114)+chr(114)+chr(111)+chr(114)+chr(115)]}")
    print(f"Report: {args.output}")


if __name__ == "__main__":
    main()