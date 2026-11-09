"""Defensive high-impact macro-event gate."""

import json
import math
import time
from pathlib import Path

from config import Config


class EconomicNewsFilter:
    HIGH_IMPACT_KEYWORDS = ("CPI", "FOMC", "NFP", "FED", "RATE", "INTEREST", "FAIZ")

    def __init__(self, events_path=None):
        self.events_path = events_path or getattr(Config, "ECONOMIC_NEWS_EVENTS_FILE", "economic_events.json")

    def evaluate(self, timestamp_ms=None, events=None):
        now_ms = self._timestamp_ms(timestamp_ms)
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        before = self._window_ms("ECONOMIC_NEWS_BLOCK_BEFORE_MINUTES", 45)
        after = self._window_ms("ECONOMIC_NEWS_BLOCK_AFTER_MINUTES", 30)
        source = events if events is not None else self._load_events()
        if not isinstance(source, (list, tuple)):
            source = []

        blocking = []
        for event in source:
            if not isinstance(event, dict):
                continue
            impact = str(event.get("impact", "")).strip().upper()
            title = str(event.get("title") or event.get("name") or "").strip().upper()
            event_time = self._event_time_ms(event)
            if event_time is None:
                continue
            keyword_match = any(keyword in title for keyword in self.HIGH_IMPACT_KEYWORDS)
            if impact not in {"HIGH", "3", "HIGH_IMPACT"} and not keyword_match:
                continue
            if event_time - before <= now_ms <= event_time + after:
                blocking.append(event)

        return {
            "active": bool(blocking),
            "trade_allowed": not blocking,
            "confidence": 100 if not blocking else 15,
            "blocking_events": blocking,
            "reason": "High-impact macro news window" if blocking else "No high-impact news window",
        }

    @staticmethod
    def _timestamp_ms(value):
        if value is None:
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(numeric):
            return None
        return int(numeric if numeric > 10_000_000_000 else numeric * 1000)

    @staticmethod
    def _window_ms(config_name, default_minutes):
        try:
            minutes = float(getattr(Config, config_name, default_minutes))
        except (TypeError, ValueError, OverflowError):
            minutes = float(default_minutes)
        if not math.isfinite(minutes):
            minutes = float(default_minutes)
        return int(max(0.0, minutes) * 60_000)

    def _load_events(self):
        path = Path(self.events_path)
        if not path.exists():
            return []
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return []
        if isinstance(payload, dict):
            payload = payload.get("events", [])
        return [event for event in payload if isinstance(event, dict)] if isinstance(payload, list) else []

    def _event_time_ms(self, event):
        for key in ("timestamp_ms", "timestamp", "time"):
            if key in event and event[key] is not None:
                return self._timestamp_ms(event[key])
        return None
