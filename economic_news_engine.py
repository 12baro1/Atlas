"""Economic news filter for high-impact macro events."""

import json
import time
from pathlib import Path

from config import Config


class EconomicNewsFilter:
    HIGH_IMPACT_KEYWORDS = ("CPI", "FOMC", "NFP", "FED", "RATE", "INTEREST", "FAIZ")

    def __init__(self, events_path=None):
        self.events_path = events_path or getattr(Config, "ECONOMIC_NEWS_EVENTS_FILE", "economic_events.json")

    def evaluate(self, timestamp_ms=None, events=None):
        now_ms = int(timestamp_ms or time.time() * 1000)
        before = int(getattr(Config, "ECONOMIC_NEWS_BLOCK_BEFORE_MINUTES", 45)) * 60 * 1000
        after = int(getattr(Config, "ECONOMIC_NEWS_BLOCK_AFTER_MINUTES", 30)) * 60 * 1000
        events = events if events is not None else self._load_events()
        blocking = []
        for event in events:
            impact = str(event.get("impact", "")).upper()
            title = str(event.get("title") or event.get("name") or "").upper()
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

    def _load_events(self):
        path = Path(self.events_path)
        if not path.exists():
            return []
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if isinstance(payload, dict):
                return payload.get("events", [])
            return payload if isinstance(payload, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _event_time_ms(self, event):
        value = event.get("time") or event.get("timestamp") or event.get("timestamp_ms")
        try:
            numeric = int(float(value))
        except (TypeError, ValueError):
            return None
        return numeric if numeric > 10_000_000_000 else numeric * 1000
