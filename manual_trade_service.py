"""Shared manual trade backend for TUI and Telegram flows."""

from __future__ import annotations

from contextlib import nullcontext
from typing import Callable


class ManualTradeService:
    """Single backend for manual trade lifecycle operations."""

    def __init__(self, journal, refresh_learning: Callable[[], object] | None = None, lock=None):
        self.journal = journal
        self.refresh_learning = refresh_learning
        self.lock = lock

    def _guard(self):
        return self.lock if self.lock is not None else nullcontext()

    def open_trade(self, *, signal_id, actual_entry=None, position_size=None, actual_stop=None, actual_tp=None):
        if self.journal is None:
            return None, "journal_unavailable"
        with self._guard():
            manual, code = self.journal.open_manual_trade(
                signal_id=signal_id,
                actual_entry=actual_entry,
                actual_stop=actual_stop,
                actual_tp=actual_tp,
                position_size=position_size,
            )
        return manual, code

    def mark_not_traded(self, *, signal_id):
        if self.journal is None:
            return None, "journal_unavailable"
        with self._guard():
            manual, code = self.journal.mark_manual_not_traded(signal_id=signal_id)
        return manual, code

    def close_trade(self, *, signal_id, result, actual_exit=None):
        if self.journal is None:
            return None, "journal_unavailable"

        with self._guard():
            manual = self.journal.find_manual_trade(signal_id=signal_id)
            if manual is None:
                return None, "manual_not_found"
            if manual.get("status") == "NOT_TRADED":
                return manual, "not_traded"

            normalized = self._normalize_result(result)
            manual, code = self.journal.close_manual_trade(
                signal_id=signal_id,
                actual_exit=actual_exit,
                result=normalized,
                manual_exit_reason=str(result or normalized or "manual_close"),
            )
        if code == "closed":
            self._refresh_learning_safe()
        return manual, code

    def resolve_signal_id(self, *, signal_id=None, symbol=None, direction=None):
        if signal_id:
            return signal_id
        if self.journal is None:
            return None

        direction = str(direction or "").upper().strip() or None
        symbol = str(symbol or "").strip() or None

        with self._guard():
            candidates = self.journal.signal_outcomes(symbol=symbol)
        if direction:
            directional = [item for item in candidates if str(item.get("direction") or "").upper() == direction]
            if directional:
                return directional[0].get("signal_id")
        return candidates[0].get("signal_id") if candidates else None

    def _refresh_learning_safe(self):
        if self.refresh_learning is None:
            return
        try:
            self.refresh_learning()
        except Exception:
            return

    def _normalize_result(self, result):
        if result is None:
            return None
        value = str(result or "").upper().strip()
        if not value:
            return None
        aliases = {
            "TP": "WIN",
            "SL": "LOSS",
            "EARLY": "EARLY_EXIT",
            "ERKEN_CIKTIM": "EARLY_EXIT",
            "ERKEN_CIKIS": "EARLY_EXIT",
        }
        normalized = aliases.get(value, value)
        allowed = {"WIN", "LOSS", "BREAKEVEN", "EARLY_EXIT", "MANUAL_CLOSE", "CANCELLED"}
        return normalized if normalized in allowed else "MANUAL_CLOSE"
