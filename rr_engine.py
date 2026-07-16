"""
rr_engine.py
Atlas SMC Engine
"""

class RREngine:
    """
    Risk / Reward validation engine.
    """

    def validate(self, entry, stop_loss, take_profit, minimum_rr=3.0):

        if entry is None or stop_loss is None or take_profit is None:
            return {
                "valid": False,
                "rr": 0
            }

        risk = abs(entry - stop_loss)
        reward = abs(take_profit - entry)

        if risk == 0:
            return {
                "valid": False,
                "rr": 0
            }

        rr = reward / risk

        return {
            "valid": rr >= minimum_rr,
            "rr": round(rr, 2),
            "risk": risk,
            "reward": reward,
            "minimum_rr": minimum_rr
        }
