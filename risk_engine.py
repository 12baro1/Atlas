"""
risk_engine.py
Atlas Risk Engine v2
"""

class RiskEngine:

    def calculate(self, entry, stop_loss):

        if entry is None or stop_loss is None:
            return None

        risk = abs(entry - stop_loss)

        if risk <= 0:
            return None

        if entry > stop_loss:

            side = "LONG"

            tp1 = entry + risk * 2
            tp2 = entry + risk * 3
            tp3 = entry + risk * 5

        else:

            side = "SHORT"

            tp1 = entry - risk * 2
            tp2 = entry - risk * 3
            tp3 = entry - risk * 5

        return {

            "side": side,

            "entry": entry,

            "stop_loss": stop_loss,

            "risk": risk,

            "tp1": tp1,

            "tp2": tp2,

            "tp3": tp3,

            "rr": 2.0

        }
        
