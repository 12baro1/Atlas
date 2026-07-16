"""
position_manager.py
Atlas SMC Engine
"""

class PositionManager:
    """
    Calculates position size based on account balance and risk.
    """

    def calculate(self, balance, risk_percent, entry, stop_loss):

        if balance <= 0 or risk_percent <= 0:
            return {"valid": False}

        risk_amount = balance * (risk_percent / 100)

        distance = abs(entry - stop_loss)

        if distance <= 0:
            return {"valid": False}

        position_size = risk_amount / distance

        return {
            "valid": True,
            "balance": balance,
            "risk_percent": risk_percent,
            "risk_amount": round(risk_amount, 2),
            "position_size": position_size,
            "entry": entry,
            "stop_loss": stop_loss
        }
