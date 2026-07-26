"""Adaptive learning layer based on closed trade performance."""

import json
from pathlib import Path


class LearningEngine:
    def __init__(self, path="atlas_learning.json"):
        self.path = Path(path)
        self.stats = {"setups": {}}
        self.load()

    def load(self):
        if not self.path.exists():
            return self.stats
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if isinstance(payload, dict):
                self.stats.update(payload)
                self.stats.setdefault("setups", {})
        except (OSError, json.JSONDecodeError):
            pass
        return self.stats

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(self.stats, handle, ensure_ascii=False, indent=2)

    def record_closed_trade(self, trade):
        setup = self._setup_key(trade)
        bucket = self.stats.setdefault("setups", {}).setdefault(setup, self._empty_bucket())
        bucket["total"] += 1
        result = trade.get("result")
        if result == "WIN":
            bucket["wins"] += 1
        elif result == "LOSS":
            bucket["losses"] += 1
        bucket["confidence_sum"] += float(trade.get("confidence") or 0)
        grade = str(trade.get("grade") or "UNKNOWN")
        bucket.setdefault("grade_counts", {})
        bucket["grade_counts"][grade] = bucket["grade_counts"].get(grade, 0) + 1
        bucket["last_reason"] = trade.get("close_reason") or trade.get("result")
        bucket["weight"] = self._weight(bucket)
        self.save()
        return bucket

    def adjustments_for(self, setup_quality):
        module_scores = (setup_quality or {}).get("module_scores") or {}
        adjustments = {}
        for name in module_scores:
            bucket = self.stats.get("setups", {}).get(name)
            if not bucket or bucket.get("total", 0) < 5:
                adjustments[name] = 1.0
            else:
                adjustments[name] = bucket.get("weight", 1.0)
        return adjustments

    def apply_to_setup_quality(self, setup_quality):
        if not setup_quality or not setup_quality.get("module_scores"):
            return setup_quality
        adjusted = dict(setup_quality)
        module_scores = {k: dict(v) for k, v in setup_quality.get("module_scores", {}).items()}
        weights = self.adjustments_for(setup_quality)
        total = 0
        count = 0
        for name, payload in module_scores.items():
            payload["learned_weight"] = weights.get(name, 1.0)
            payload["score"] = int(max(0, min(100, payload.get("score", 0) * payload["learned_weight"])))
            total += payload["score"]
            count += 1
        adjusted["module_scores"] = module_scores
        if count:
            adjusted["score"] = int(max(0, min(100, (setup_quality.get("score", 0) * 0.7) + ((total / count) * 0.3))))
            adjusted["confidence"] = adjusted["score"]
            adjusted["trade_allowed"] = adjusted["trade_allowed"] and adjusted["score"] >= 58
        adjusted["learning_adjustments"] = weights
        return adjusted

    def setup_success_rates(self):
        output = {}
        for setup, bucket in self.stats.get("setups", {}).items():
            total = bucket.get("total", 0)
            output[setup] = {
                "total": total,
                "winrate": round(bucket.get("wins", 0) / total * 100, 2) if total else 0,
                "weight": bucket.get("weight", 1.0),
            }
        return output

    def _setup_key(self, trade):
        metadata = trade.get("metadata") or {}
        return metadata.get("setup_type") or trade.get("setup_type") or trade.get("side") or "UNKNOWN"

    def _empty_bucket(self):
        return {"total": 0, "wins": 0, "losses": 0, "confidence_sum": 0.0, "grade_counts": {}, "weight": 1.0}

    def _weight(self, bucket):
        total = bucket.get("total", 0)
        if total < 5:
            return 1.0
        winrate = bucket.get("wins", 0) / total
        if winrate >= 0.62:
            return 1.12
        if winrate <= 0.42:
            return 0.88
        return 1.0
