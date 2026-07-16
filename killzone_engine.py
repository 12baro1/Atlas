"""
killzone_engine.py
Atlas SMC Engine
"""

from datetime import datetime, timezone


class KillZoneEngine:
    """
    London & New York Kill Zone Filter
    Times are UTC.
    """

    LONDON_START = 7
    LONDON_END = 10

    NEWYORK_START = 12
    NEWYORK_END = 15

    def detect(self, timestamp_ms):

        dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        hour = dt.hour

        london = self.LONDON_START <= hour < self.LONDON_END
        newyork = self.NEWYORK_START <= hour < self.NEWYORK_END

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
