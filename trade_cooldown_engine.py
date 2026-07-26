"""Trade cooldown and duplicate-position guard."""

import time

from config import Config


class TradeCooldownEngine:
    def __init__(self):
        self.last_signals = {}

    def evaluate(self, symbol, direction, open_positions=None, now_ts=None):
        now_ts = float(now_ts or time.time())
        cooldown_minutes = float(getattr(Config, "TRADE_COOLDOWN_MINUTES", 180))
        for position in open_positions or []:
            if position.get("symbol") == symbol and position.get("status") == "OPEN":
                return {"trade_allowed": False, "active": True, "reason": "Open position already exists", "cooldown_remaining_seconds": None}
        key = (symbol, direction)
        last_ts = self.last_signals.get(key)
        if last_ts is not None and cooldown_minutes > 0:
            elapsed = now_ts - last_ts
            cooldown_seconds = cooldown_minutes * 60
            if elapsed < cooldown_seconds:
                return {
                    "trade_allowed": False,
                    "active": True,
                    "reason": "Trade cooldown active",
                    "cooldown_remaining_seconds": round(cooldown_seconds - elapsed, 2),
                }
        return {"trade_allowed": True, "active": False, "reason": "Cooldown clear", "cooldown_remaining_seconds": 0}

    def register_signal(self, symbol, direction, now_ts=None):
        if direction in ["LONG", "SHORT"]:
            self.last_signals[(symbol, direction)] = float(now_ts or time.time())
