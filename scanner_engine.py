"""Scanner aggregation for complete, centrally approved Atlas setups."""

import math


def _finite_number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


class ScannerEngine:
    def __init__(self):
        self.trades = []

    def add(self, symbol, result_payload):
        """Convert one final engine payload into a scanner row."""
        if not isinstance(result_payload, dict):
            return

        analysis = result_payload.get("analysis") or {}
        signal = result_payload.get("signal") or {}
        risk = result_payload.get("risk") or {}
        decision = result_payload.get("decision") or {}
        rr = result_payload.get("rr") or {}
        if not all(isinstance(item, dict) for item in (analysis, signal, risk, decision)):
            return

        direction = signal.get("signal")
        entry = _finite_number(risk.get("entry"))
        stop = _finite_number(risk.get("stop_loss"))
        targets = [_finite_number(risk.get(key)) for key in ("tp1", "tp2", "tp3")]
        rr_value = rr.get("rr") if isinstance(rr, dict) else rr
        rr_value = _finite_number(rr_value)
        levels_valid = (
            entry is not None and stop is not None
            and all(value is not None for value in targets)
            and rr_value is not None and rr_value > 0
        )
        if levels_valid and direction == "LONG":
            levels_valid = stop < entry < targets[0] < targets[1] < targets[2]
        elif levels_valid and direction == "SHORT":
            levels_valid = stop > entry > targets[0] > targets[1] > targets[2]
        else:
            levels_valid = False

        approved = (
            direction in ("LONG", "SHORT")
            and decision.get("action") in ("EXECUTE", "EXECUTE_WITH_CAUTION")
            and risk.get("risk_setup_valid") is True
            and str((analysis.get("entry") or {}).get("entry_type", "")).upper() in ("MARKET", "LIMIT")
            and levels_valid
        )
        confluence = analysis.get("confluence") or {}
        quality = analysis.get("setup_quality") or {}
        phase = analysis.get("market_phase") or {}
        entry_data = analysis.get("entry") or {}
        self.trades.append({
            "symbol": symbol,
            "direction": direction,
            "score": _finite_number(confluence.get("score")) or 0.0,
            "grade": quality.get("grade"),
            "stars": quality.get("stars", 0),
            "entry": entry,
            "entry_type": str(entry_data.get("entry_type") or "NONE").upper(),
            "stop_loss": stop,
            "tp1": targets[0],
            "tp2": targets[1],
            "tp3": targets[2],
            "confidence": _finite_number(signal.get("confidence")) or 0.0,
            "decision": decision.get("action"),
            "tradable": bool(approved),
            "rr": rr_value,
            "market_phase": phase.get("phase"),
            "setup": quality.get("setup"),
            "reasons": confluence.get("reasons", []),
        })

    def results(self):
        return sorted(
            self.trades,
            key=lambda item: (
                bool(item.get("tradable")),
                _finite_number(item.get("rr")) or 0.0,
                _finite_number(item.get("score")) or 0.0,
            ),
            reverse=True,
        )

    def top(self, limit=20):
        try:
            limit = max(0, int(limit))
        except (TypeError, ValueError, OverflowError):
            limit = 20
        return self.results()[:limit]

    def clear(self):
        self.trades.clear()

    def summary(self):
        if not self.trades:
            return {"total": 0, "best": None, "executable": []}
        ordered = self.results()
        executable = [item for item in ordered if item.get("tradable") is True]
        return {
            "total": len(self.trades),
            "best": ordered[0],
            "executable": executable[:10],
        }
