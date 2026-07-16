"""
session_filter.py
Atlas SMC Engine
"""

from datetime import datetime, timezone


class SessionFilter:
    """
    Trading session filter.
    """

    def check(self, timestamp_ms):

        dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)

        weekday = dt.weekday()   # 0=Mon ... 6=Sun
        hour = dt.hour

        weekend = weekday >= 5

        london = 7 <= hour < 10
        newyork = 12 <= hour < 15
        overlap = 12 <= hour < 14

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
