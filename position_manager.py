"""
position_manager.py
Atlas SMC Engine v2
"""

class PositionManager:

    def __init__(self):

        self.positions = []

    def open(self, symbol, trade):

        if trade is None:
            return

        self.positions.append({
            "symbol": symbol,
            "side": trade["side"],
            "entry": trade["entry"],
            "stop_loss": trade["stop_loss"],
            "tp1": trade["tp1"],
            "tp2": trade["tp2"],
            "tp3": trade["tp3"],
            "status": "OPEN",
            "hit_tp1": False,
            "hit_tp2": False,
            "hit_tp3": False
        })

    def update(self, symbol, price):

        for pos in self.positions:

            if pos["symbol"] != symbol:
                continue

            if pos["status"] != "OPEN":
                continue

            if pos["side"] == "LONG":

                if price <= pos["stop_loss"]:
                    pos["status"] = "STOP"

                if price >= pos["tp1"]:
                    pos["hit_tp1"] = True

                if price >= pos["tp2"]:
                    pos["hit_tp2"] = True

                if price >= pos["tp3"]:
                    pos["hit_tp3"] = True
                    pos["status"] = "CLOSED"

            else:

                if price >= pos["stop_loss"]:
                    pos["status"] = "STOP"

                if price <= pos["tp1"]:
                    pos["hit_tp1"] = True

                if price <= pos["tp2"]:
                    pos["hit_tp2"] = True

                if price <= pos["tp3"]:
                    pos["hit_tp3"] = True
                    pos["status"] = "CLOSED"

    def open_positions(self):

        return [
            p for p in self.positions
            if p["status"] == "OPEN"
        ]

    def closed_positions(self):

        return [
            p for p in self.positions
            if p["status"] != "OPEN"
        ]

    def reset(self):

        self.positions.clear()
