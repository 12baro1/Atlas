"""
risk_engine.py
Atlas SMC Engine v2
"""

class RiskEngine:

    def calculate(
        self,
        entry,
        stop_loss,
        account_balance=1000,
        risk_percent=1.0,
        rr=3.0
    ):

        if entry is None or stop_loss is None:
            return None

        risk = abs(entry - stop_loss)

        if risk <= 0:
            return None

        # LONG / SHORT
        if entry > stop_loss:

            side = "LONG"

            tp1 = entry + risk
            tp2 = entry + (risk * 2)
            tp3 = entry + (risk * rr)

        else:

            side = "SHORT"

            tp1 = entry - risk
            tp2 = entry - (risk * 2)
            tp3 = entry - (risk * rr)

        capital_risk = account_balance * (risk_percent / 100)

        position_size = capital_risk / risk

        return {

            "side": side,

            "entry": entry,

            "stop_loss": stop_loss,

            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,

            "risk": risk,

            "rr": rr,

            "risk_percent": risk_percent,

            "capital_at_risk": capital_risk,

            "position_size": position_size
        }
        
