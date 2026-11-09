"""
session_filter.py
Atlas SMC Engine
"""

from datetime import datetime, timezone

from config import Config


class SessionFilter:
    """
    Trading session filter.
    """

    def check(self, timestamp_ms):

        dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)

        weekday = dt.weekday()   # 0=Mon ... 6=Sun
        hour = dt.hour

        weekend = weekday >= 5

        london_start = int(getattr(Config, "LONDON_START", 7))
        london_end = int(getattr(Config, "LONDON_END", 10))
        newyork_start = int(getattr(Config, "NEWYORK_START", 12))
        newyork_end = int(getattr(Config, "NEWYORK_END", 15))

        london = london_start <= hour < london_end
        newyork = newyork_start <= hour < newyork_end
        # The overlap exists only when the configured windows are both active.
        # The former end+2 expression could report impossible hours as overlap.
        overlap = london and newyork

        active = (london or newyork) and not weekend

        return {
            "active": active,
            "weekend": weekend,
            "london": london,
            "newyork": newyork,
            "overlap": overlap,
            "weekday": weekday,
            "hour": hour
        }
