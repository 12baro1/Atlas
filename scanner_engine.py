"""Scanner aggregation for the canonical, strategy-selected trade plan."""

import math

from utils.signal_card import build_selected_strategy_card, build_signal_card


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
        """Convert the same canonical plan used by the terminal into a scanner row."""
        if not isinstance(result_payload, dict):
            return
        card = (
            build_selected_strategy_card(result_payload)
            if isinstance(result_payload.get("strategy_lab"), dict)
            else build_signal_card(result_payload)
        )
        is_strategy_plan = isinstance(result_payload.get("strategy_lab"), dict)
        source_risk = result_payload.get("risk") or {}
        source_rr = result_payload.get("rr") or {}
        direction = card.get("direction") if is_strategy_plan else (result_payload.get("signal") or {}).get("signal")
        entry = _finite_number(card.get("entry") if is_strategy_plan else source_risk.get("entry"))
        stop = _finite_number(card.get("stop_loss") if is_strategy_plan else source_risk.get("stop_loss"))
        target_source = (card.get("tp_levels") or []) if is_strategy_plan else [source_risk.get(key) for key in ("tp1", "tp2", "tp3")]
        targets = [_finite_number(value) for value in target_source]
        rr_source = card.get("rr") if is_strategy_plan else (source_rr.get("rr") if isinstance(source_rr, dict) else source_rr)
        rr = _finite_number(rr_source)
        entry_type = str(card.get("entry_type") or "NONE").upper()
        levels_valid = (
            entry is not None and stop is not None and len(targets) == 3
            and all(value is not None for value in targets)
            and rr is not None and rr > 0
        )
        if levels_valid and direction == "LONG":
            levels_valid = stop < entry < targets[0] and all(a < b for a, b in zip(targets, targets[1:]))
        elif levels_valid and direction == "SHORT":
            levels_valid = stop > entry > targets[0] and all(a > b for a, b in zip(targets, targets[1:]))
        else:
            levels_valid = False
        entry_validation_ok = card.get("entry_valid") is True if is_strategy_plan else entry is not None
        risk_validation_ok = card.get("risk_setup_valid") is True if is_strategy_plan else source_risk.get("risk_setup_valid") is True
        approved = (
            direction in ("LONG", "SHORT")
            and card.get("decision_action") in ("EXECUTE", "EXECUTE_WITH_CAUTION")
            and entry_validation_ok
            and risk_validation_ok
            and entry_type in ("MARKET", "LIMIT")
            and levels_valid
        )
        strategy = card.get("strategy") or card.get("strategy_id")
        reasons = list(card.get("supporting_evidence") or [])
        self.trades.append({
            "symbol": symbol,
            "direction": direction,
            "score": _finite_number(card.get("confluence")) or 0.0,
            "grade": card.get("grade"),
            "stars": 0,
            "entry": entry,
            "entry_type": entry_type,
            "stop_loss": stop,
            "tp1": targets[0] if len(targets) > 0 else None,
            "tp2": targets[1] if len(targets) > 1 else None,
            "tp3": targets[2] if len(targets) > 2 else None,
            "confidence": _finite_number(card.get("confidence")) or 0.0,
            "decision": card.get("decision_action"),
            "tradable": bool(approved),
            "rr": rr,
            "market_phase": card.get("market_phase"),
            "setup": strategy or card.get("setup_thesis"),
            "strategy_id": card.get("strategy_id"),
            "reasons": reasons,
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
        return {"total": len(self.trades), "best": ordered[0], "executable": executable[:10]}
