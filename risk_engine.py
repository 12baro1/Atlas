"""
risk_engine.py
Atlas Risk Engine v4
"""

class RiskEngine:

    def calculate(self, entry, stop_loss, dynamic_tp=None):

        if entry is None or stop_loss is None:
            return None

        risk = abs(entry - stop_loss)

        if risk <= 0:
            return None

        account_balance = 1000.0
        risk_percent = 1.0

        capital_at_risk = account_balance * (risk_percent / 100)
        position_size = capital_at_risk / risk

        side = "LONG" if entry > stop_loss else "SHORT"

        tp1 = None
        tp2 = None
        tp3 = None
        rr = None

        if dynamic_tp is not None:

            tp1 = dynamic_tp.get("tp1")
            tp2 = dynamic_tp.get("tp2")
            tp3 = dynamic_tp.get("tp3")

            if tp3 is not None:
                rr = round(abs(tp3 - entry) / risk, 2)

        return {

            "side": side,

            "entry": round(entry, 8),

            "stop_loss": round(stop_loss, 8),

            "risk": round(risk, 8),

            "capital_at_risk": round(capital_at_risk, 2),

            "position_size": round(position_size, 4),

            "tp1": tp1,

            "tp2": tp2,

            "tp3": tp3,

            "rr": rr

        }
