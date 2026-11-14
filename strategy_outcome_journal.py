"""Persistent, strategy-isolated realized outcome journal.

Only closed, realized outcomes with an explicit cost-inclusive net-R value can
enter the performance gate. Backtest IS and untouched OOS samples stay separate.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
from collections import defaultdict


VALID_STRATEGIES = {
    "trend_pullback", "volatility_breakout", "mean_reversion",
    "liquidation_cascade", "orderflow_momentum", "relative_strength", "smc",
}


class StrategyOutcomeJournal:
    def __init__(self, path=None):
        self.path = path or os.getenv("ATLAS_STRATEGY_OUTCOMES_PATH", "data/strategy_outcomes.jsonl")
        self._lock = threading.RLock()
        self._records = None

    def _load(self):
        if self._records is not None:
            return self._records
        records = []
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        item = json.loads(line)
                    except (TypeError, ValueError):
                        continue
                    if isinstance(item, dict) and item.get("trade_id") and item.get("strategy_id") in VALID_STRATEGIES:
                        records.append(item)
        except FileNotFoundError:
            pass
        self._records = records
        return records

    def record_outcome(self, *, strategy_id, trade_id, run_id, run_created_at_ms, split, net_r, gross_r, cost_r, cost_model_id, closed_at_ms, costs_included, symbol="UNKNOWN", source_revision="unknown", regime="UNKNOWN"):
        strategy = str(strategy_id or "").strip()
        identifier = str(trade_id or "").strip()
        replay_id = str(run_id or "").strip()
        sample = str(split or "").lower()
        try:
            result_r = float(net_r)
            gross_result_r = float(gross_r)
            cost_result_r = float(cost_r)
            closed_at = int(closed_at_ms)
            run_created = int(run_created_at_ms)
        except (TypeError, ValueError, OverflowError):
            return {"accepted": False, "reason": "invalid_numeric_outcome"}
        if strategy not in VALID_STRATEGIES or not identifier or not replay_id or sample not in {"is", "oos"}:
            return {"accepted": False, "reason": "invalid_strategy_trade_or_split"}
        model_id = str(cost_model_id or "").strip()
        if (
            not all(math.isfinite(value) for value in (result_r, gross_result_r, cost_result_r))
            or closed_at <= 0
            or run_created <= 0
            or costs_included is not True
            or not model_id
            or abs(result_r - (gross_result_r - cost_result_r)) > 1e-5
        ):
            return {"accepted": False, "reason": "outcome_requires_reconciled_gross_cost_net_r_and_cost_model"}

        record = {
            "strategy_id": strategy,
            "trade_id": identifier,
            "run_id": replay_id,
            "run_created_at_ms": run_created,
            "split": sample,
            "net_r": round(result_r, 8),
            "gross_r": round(gross_result_r, 8),
            "cost_r": round(cost_result_r, 8),
            "cost_model_id": model_id,
            "closed_at_ms": closed_at,
            "costs_included": True,
            "symbol": str(symbol or "UNKNOWN"),
            "source_revision": str(source_revision or "unknown"),
            "regime": str(regime or "UNKNOWN"),
        }
        with self._lock:
            records = self._load()
            if any(item.get("trade_id") == identifier for item in records):
                return {"accepted": False, "reason": "duplicate_trade_id"}
            parent = os.path.dirname(self.path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            records.append(record)
        return {"accepted": True, "record": dict(record)}

    @staticmethod
    def _summarize(values):
        count = len(values)
        if not count:
            return {
                "trades": 0, "expectancy_r": None, "profit_factor": None,
                "expectancy_std_r": None,
            }
        mean = sum(values) / count
        wins = sum(value for value in values if value > 0)
        losses = -sum(value for value in values if value < 0)
        variance = sum((value - mean) ** 2 for value in values) / max(1, count - 1)
        return {
            "trades": count,
            "expectancy_r": round(mean, 8),
            "profit_factor": round(wins / losses, 8) if losses > 0 else (999.0 if wins > 0 else 0.0),
            "expectancy_std_r": round(math.sqrt(variance), 8),
        }

    def current_revision(self):
        """Fingerprint strategy logic and replay code, excluding unrelated docs/UI commits."""
        root = os.path.dirname(os.path.abspath(__file__))
        digest = hashlib.sha256()
        for filename in (
            "strategy_lab.py", "strategy_performance.py",
            "strategy_backtest.py", "strategy_outcome_journal.py",
            "historical_derivatives.py", "microstructure_archive.py",
            "data_engine.py", "orderbook_engine.py", "engine.py",
            "risk_engine.py", "rr_engine.py", "dynamic_tp_engine.py",
            "timing.py", "utils/signal_card.py",
        ):
            path = os.path.join(root, filename)
            try:
                with open(path, "rb") as handle:
                    digest.update(filename.encode("utf-8"))
                    digest.update(handle.read())
            except OSError:
                return "unknown"
        return "sha256:" + digest.hexdigest()

    def performance_snapshot(self, symbol=None, regime=None, source_revision=None, run_id=None):
        with self._lock:
            records = list(self._load())
        requested_symbol = str(symbol).upper() if symbol else None
        requested_regime = str(regime).upper() if regime else None
        requested_revision = str(source_revision) if source_revision else None
        requested_run = str(run_id) if run_id else None
        matching_records = [
            item for item in records
            if (not requested_symbol or str(item.get("symbol") or "").upper() == requested_symbol)
            and (not requested_regime or str(item.get("regime") or "").upper() == requested_regime)
            and (not requested_revision or str(item.get("source_revision") or "unknown") == requested_revision)
        ]
        if requested_run is None and matching_records:
            latest = max(matching_records, key=lambda item: int(item.get("run_created_at_ms") or 0))
            requested_run = str(latest.get("run_id") or "")
        grouped = defaultdict(lambda: {"is": [], "oos": []})
        for item in matching_records:
            if item.get("costs_included") is not True:
                continue
            if requested_run and str(item.get("run_id") or "") != requested_run:
                continue
            split = item.get("split")
            strategy = item.get("strategy_id")
            if split in {"is", "oos"} and strategy in VALID_STRATEGIES:
                try:
                    value = float(item.get("net_r"))
                except (TypeError, ValueError, OverflowError):
                    continue
                if math.isfinite(value):
                    grouped[strategy][split].append(value)

        output = {}
        for strategy, samples in grouped.items():
            ins = self._summarize(samples["is"])
            oos = self._summarize(samples["oos"])
            output[strategy] = {
                "is_trades": ins["trades"],
                "is_expectancy_r": ins["expectancy_r"],
                "is_profit_factor": ins["profit_factor"],
                "is_expectancy_std_r": ins["expectancy_std_r"],
                "oos_trades": oos["trades"],
                "oos_expectancy_r": oos["expectancy_r"],
                "oos_profit_factor": oos["profit_factor"],
            }
        return output
