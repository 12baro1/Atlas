"""Manual Telegram trade quality scoring and historical performance gate."""

from __future__ import annotations

from collections import defaultdict


class ManualTradeQualityGate:
    """Score a setup before it is sent to Telegram for manual trading."""

    def __init__(self, config):
        self.config = config

    def evaluate(self, *, symbol, signal, entry, risk, decision, confluence, market_phase, trade_journal=None):
        signal = signal or {}
        entry = entry or {}
        risk = risk or {}
        decision = decision or {}
        confluence = confluence or {}
        market_phase = market_phase or {}

        blockers = []
        warnings = []
        components = {}

        confidence = self._num(signal.get("confidence"), 0)
        confluence_score = self._num(confluence.get("score"), 0)
        rr = self._resolve_rr(risk)
        decision_score = self._num(decision.get("score"), 0)

        components["confidence"] = min(25, confidence * 0.25)
        components["confluence"] = min(20, confluence_score * 0.20)
        components["rr"] = min(20, (rr or 0) / max(float(getattr(self.config, "TELEGRAM_MIN_RR", 3.0)), 0.01) * 15)
        components["decision"] = 15 if decision.get("action") == "EXECUTE" else 5 if decision.get("action") == "EXECUTE_WITH_CAUTION" else 0
        components["phase"] = 10 if self._phase_allowed(market_phase, decision) else 0
        components["risk"] = 10 if decision.get("risk_valid", True) and entry.get("valid", False) else 0

        historical = self._historical_context(symbol=symbol, decision=decision, market_phase=market_phase, trade_journal=trade_journal)
        components["historical"] = historical["score"]
        warnings.extend(historical["warnings"])
        blockers.extend(historical["blockers"])

        score = int(max(0, min(100, round(sum(components.values())))))
        if score < float(getattr(self.config, "TELEGRAM_MIN_MANUAL_SCORE", 75)):
            blockers.append(
                f"manual score {score} < {self._fmt(getattr(self.config, 'TELEGRAM_MIN_MANUAL_SCORE', 75))}"
            )

        if decision.get("action") != "EXECUTE" and not bool(getattr(self.config, "TELEGRAM_ALLOW_CAUTION_SIGNALS", False)):
            blockers.append(f"manual gate requires EXECUTE, got {decision.get('action', 'WAIT')}")

        return {
            "score": score,
            "grade": self._grade(score),
            "allowed": len(blockers) == 0,
            "blockers": blockers,
            "warnings": warnings,
            "components": {key: round(value, 2) for key, value in components.items()},
            "historical": historical,
        }

    def _historical_context(self, *, symbol, decision, market_phase, trade_journal):
        min_trades = int(getattr(self.config, "TELEGRAM_HISTORICAL_MIN_TRADES", 20))
        min_expectancy = float(getattr(self.config, "TELEGRAM_HISTORICAL_MIN_EXPECTANCY", 0.30))
        min_profit_factor = float(getattr(self.config, "TELEGRAM_HISTORICAL_MIN_PROFIT_FACTOR", 1.30))
        strict = bool(getattr(self.config, "TELEGRAM_HISTORICAL_STRICT", False))

        result = {
            "sample_size": 0,
            "expectancy": 0,
            "profit_factor": 0,
            "winrate": 0,
            "score": 5,
            "blockers": [],
            "warnings": [],
        }

        if trade_journal is None or not hasattr(trade_journal, "_closed_trades"):
            result["warnings"].append("historical journal unavailable")
            return result

        closed = list(trade_journal._closed_trades())
        if not closed:
            result["warnings"].append("no closed trades for historical filter")
            return result

        setup = decision.get("action") or "UNKNOWN"
        phase = (market_phase or {}).get("phase") or decision.get("market_phase") or "UNKNOWN"
        candidates = [
            trade for trade in closed
            if trade.get("symbol") == symbol
            or (trade.get("analysis", {}).get("decision", {}).get("action") or trade.get("side")) == setup
            or trade.get("market_phase") == phase
        ]
        if not candidates:
            candidates = closed

        metrics = self._metrics(candidates)
        result.update(metrics)
        result["sample_size"] = len(candidates)

        if len(candidates) < min_trades:
            result["warnings"].append(f"historical sample too small: {len(candidates)} < {min_trades}")
            result["score"] = 5 if not strict else 0
            if strict:
                result["blockers"].append(result["warnings"][-1])
            return result

        if metrics["expectancy"] < min_expectancy:
            result["blockers"].append(f"historical expectancy {self._fmt(metrics['expectancy'])} < {self._fmt(min_expectancy)}")
        if metrics["profit_factor"] < min_profit_factor:
            result["blockers"].append(f"historical profit factor {self._fmt(metrics['profit_factor'])} < {self._fmt(min_profit_factor)}")

        if not result["blockers"]:
            result["score"] = 15
        elif metrics["expectancy"] > 0:
            result["score"] = 7
        else:
            result["score"] = 0

        return result

    def _metrics(self, trades):
        r_values = [self._num(trade.get("pnl_rr"), 0) for trade in trades]
        wins = [value for value in r_values if value > 0]
        losses = [value for value in r_values if value < 0]
        profit = sum(wins)
        loss = abs(sum(losses))
        profit_factor = profit / loss if loss > 0 else profit
        expectancy = sum(r_values) / len(r_values) if r_values else 0
        winrate = len(wins) / len(r_values) * 100 if r_values else 0
        return {
            "expectancy": round(expectancy, 4),
            "profit_factor": round(profit_factor, 4),
            "winrate": round(winrate, 2),
        }

    def _phase_allowed(self, market_phase, decision):
        allowed = set(getattr(self.config, "TELEGRAM_ALLOWED_MARKET_PHASES", ("Expansion", "Trending", "Reversal")))
        phase = str((market_phase or {}).get("phase") or decision.get("market_phase") or "").strip()
        return bool(phase and phase in allowed)

    def _resolve_rr(self, risk):
        for key in ("selected_rr", "rr"):
            value = self._num((risk or {}).get(key), None)
            if value is not None and value > 0:
                return value
        rr_by_tp = (risk or {}).get("rr_by_tp")
        if isinstance(rr_by_tp, dict):
            values = [self._num(value, None) for value in rr_by_tp.values()]
            values = [value for value in values if value is not None and value > 0]
            if values:
                return max(values)
        return None

    def _grade(self, score):
        if score >= 90:
            return "A+"
        if score >= 80:
            return "A"
        if score >= 70:
            return "B"
        if score >= 60:
            return "C"
        return "D"

    def _num(self, value, default=0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _fmt(self, value):
        return f"{float(value):.2f}".rstrip("0").rstrip(".")
