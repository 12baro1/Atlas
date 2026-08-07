"""
killzone_engine.py
Atlas SMC Engine
"""

from datetime import datetime, timezone

from config import Config


class KillZoneEngine:
    """
    London & New York Kill Zone Filter
    Times are UTC.
    """

    def detect(self, timestamp_ms):

        dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        hour = dt.hour

        london_start = int(getattr(Config, "LONDON_START", 7))
        london_end = int(getattr(Config, "LONDON_END", 10))
        newyork_start = int(getattr(Config, "NEWYORK_START", 12))
        newyork_end = int(getattr(Config, "NEWYORK_END", 15))

        london = london_start <= hour < london_end
        newyork = newyork_start <= hour < newyork_end

        active = london or newyork

        if london:
            zone = "LONDON"
        elif newyork:
            zone = "NEWYORK"
        else:
            zone = "OFF_SESSION"

        return {
            "active": active,
            "zone": zone,
            "hour": hour
        }
