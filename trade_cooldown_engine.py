"""Trade cooldown and duplicate-position guard."""

import math
import time

from config import Config


class TradeCooldownEngine:
    def __init__(self):
        self.last_signals = {}

    @staticmethod
    def _finite(value, fallback):
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return fallback
        return number if math.isfinite(number) else fallback

    def evaluate(self, symbol, direction, open_positions=None, now_ts=None):
        now_ts = self._finite(time.time() if now_ts is None else now_ts, time.time())
        cooldown_minutes = max(
            0.0,
            self._finite(getattr(Config, "TRADE_COOLDOWN_MINUTES", 180), 180.0),
        )
        for position in open_positions or []:
            if not isinstance(position, dict):
                continue
            if position.get("symbol") == symbol and str(position.get("status", "")).upper() == "OPEN":
                return {
                    "trade_allowed": False,
                    "active": True,
                    "reason": "Open position already exists",
                    "cooldown_remaining_seconds": None,
                }

        key = (symbol, direction)
        last_ts = self.last_signals.get(key)
        if last_ts is not None and cooldown_minutes > 0:
            last_ts = self._finite(last_ts, None)
            if last_ts is not None:
                elapsed = now_ts - last_ts
                cooldown_seconds = cooldown_minutes * 60
                if 0 <= elapsed < cooldown_seconds:
                    return {
                        "trade_allowed": False,
                        "active": True,
                        "reason": "Trade cooldown active",
                        "cooldown_remaining_seconds": round(cooldown_seconds - elapsed, 2),
                    }
                if elapsed < 0:
                    return {
                        "trade_allowed": False,
                        "active": True,
                        "reason": "Last signal timestamp is in the future",
                        "cooldown_remaining_seconds": round(cooldown_seconds, 2),
                    }

        return {
            "trade_allowed": True,
            "active": False,
            "reason": "Cooldown clear",
            "cooldown_remaining_seconds": 0,
        }

    def register_signal(self, symbol, direction, now_ts=None):
        if direction in ("LONG", "SHORT"):
            timestamp = self._finite(time.time() if now_ts is None else now_ts, None)
            if timestamp is not None:
                self.last_signals[(symbol, direction)] = timestamp
