"""
htf_orderblock_engine.py
Atlas HTF Order Block Engine
"""

class HTFOrderBlockEngine:

    def detect(
        self,
        current_price,
        daily_orderblocks,
        h4_orderblocks
    ):

        valid = False
        timeframe = None
        block = None

        for ob in h4_orderblocks:

            low = min(ob["high"], ob["low"])
            high = max(ob["high"], ob["low"])

            if low <= current_price <= high:
                valid = True
                timeframe = "H4"
                block = ob
                break

        if not valid:

            for ob in daily_orderblocks:

                low = min(ob["high"], ob["low"])
                high = max(ob["high"], ob["low"])

                if low <= current_price <= high:
                    valid = True
                    timeframe = "DAILY"
                    block = ob
                    break

        return {
            "valid": valid,
            "timeframe": timeframe,
            "block": block
        }
