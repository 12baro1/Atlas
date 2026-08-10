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
        min_rr = max(float(getattr(self.config, "TELEGRAM_MIN_RR", 3.0)), 0.01)

        # Bileşen tavanları bilinçli olarak 95'te toplanacak şekilde normalize
        # edilir: 100'e yalnızca öğrenme (learning) + geçmiş (historical) etkisi
        # eklendiğinde çok yaklaşılabilir; sıradan güçlü setup'lar 100'e yapışmaz.
        components["confidence"] = min(25, confidence * 0.25)
        components["confluence"] = min(16, confluence_score * 0.16)
        components["rr"] = min(12, (rr or 0) / min_rr * 9)
        components["decision"] = 12 if decision.get("action") == "EXECUTE" else 5 if decision.get("action") == "EXECUTE_WITH_CAUTION" else 0
        components["phase"] = 8 if self._phase_allowed(market_phase, decision) else 0
        components["risk"] = 7 if decision.get("risk_valid", True) and entry.get("valid", False) else 0

        historical = self._historical_context(symbol=symbol, decision=decision, market_phase=market_phase, trade_journal=trade_journal)
        components["historical"] = self._rescale_historical(historical["score"])
        warnings.extend(historical["warnings"])
        blockers.extend(historical["blockers"])

        learning = signal.get("learning") or {}
        components["learning"] = self._learning_component(learning)

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
            "learning": dict(learning),
        }

    def _learning_component(self, learning):
        """Öğrenilen geçmiş başarıyı skor bileşenine çevirir (-5..+5).

        Eşleşme yoksa nötr (0); eşleşme varsa score_delta ile doğru orantılı
        sınırlı bir katkı verilir. Böylece skorun 100 olması istisnai kalırken
        öğrenme gerçekçi şekilde skoru etkiler.
        """
        if not isinstance(learning, dict) or not learning.get("matched"):
            return 0
        delta = int(learning.get("score_delta") or 0)
        if delta < 0:
            points = delta // 2
        else:
            points = (delta + 1) // 2
        return max(-5, min(5, points))

    def _rescale_historical(self, raw_score):
        return {15: 10, 7: 6, 5: 4, 0: 0}.get(int(raw_score), min(10, int(raw_score)))

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
