"""
risk_engine.py
Atlas SMC Engine
"""

class RiskEngine:
    """
    Risk Management v1
    """

    def calculate(self, entry, stop_loss, risk_reward=2.0):

        if entry is None or stop_loss is None:
            return None

        risk = abs(entry - stop_loss)

        if risk == 0:
            return None

        if entry > stop_loss:
            take_profit = entry + (risk * risk_reward)
            side = "BUY"
        else:
            take_profit = entry - (risk * risk_reward)
            side = "SELL"

        return {
            "side": side,
            "entry": entry,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk": risk,
            "rr": risk_reward
        }
