"""
risk_engine.py
Atlas Risk Engine v3
"""

class RiskEngine:

    def calculate(self, entry, stop_loss):

        if entry is None or stop_loss is None:
            return None

        risk = abs(entry - stop_loss)

        if risk <= 0:
            return None

        account_size = 1000.0
        risk_percent = 1.0
        risk_amount = account_size * (risk_percent / 100)

        position_size = risk_amount / risk

        if entry > stop_loss:

            side = "LONG"

            tp1 = entry + (risk * 1.5)
            tp2 = entry + (risk * 2.0)
            tp3 = entry + (risk * 3.0)

        else:

            side = "SHORT"

            tp1 = entry - (risk * 1.5)
            tp2 = entry - (risk * 2.0)
            tp3 = entry - (risk * 3.0)

        return {

            "side": side,

            "entry": round(entry, 8),

            "stop_loss": round(stop_loss, 8),

            "risk": round(risk, 8),

            "risk_amount": round(risk_amount, 2),

            "position_size": round(position_size, 4),

            "tp1": round(tp1, 8),

            "tp2": round(tp2, 8),

            "tp3": round(tp3, 8),

            "rr": 3.0

        }
