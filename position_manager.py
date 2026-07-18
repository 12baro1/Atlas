"""
position_manager.py
Atlas SMC Engine v2
"""

class PositionManager:

    def __init__(self):

        self.positions = []

    def open(self, symbol, trade):
        return self.open_with_journal(symbol, trade)

    def open_with_journal(self, symbol, trade, journal=None, analysis=None):

        if trade is None:
            return

        position = {
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
        }

        self.positions.append(position)

        if journal is not None:
            journal.register_trade(
                trade=trade,
                analysis=analysis,
                symbol=symbol,
                metadata={"event": "OPEN"},
            )

        return position

    def update(self, symbol, price):
        return self.update_with_journal(symbol, price)

    def update_with_journal(self, symbol, price, journal=None, analysis=None):

        changed_positions = []

        for pos in self.positions:

            if pos["symbol"] != symbol:
                continue

            if pos["status"] != "OPEN":
                continue

            if pos["side"] == "LONG":

                if price <= pos["stop_loss"]:
                    pos["status"] = "STOP"
                    changed_positions.append(pos)

                if price >= pos["tp1"]:
                    pos["hit_tp1"] = True

                if price >= pos["tp2"]:
                    pos["hit_tp2"] = True

                if price >= pos["tp3"]:
                    pos["hit_tp3"] = True
                    pos["status"] = "CLOSED"
                    changed_positions.append(pos)

            else:

                if price >= pos["stop_loss"]:
                    pos["status"] = "STOP"
                    changed_positions.append(pos)

                if price <= pos["tp1"]:
                    pos["hit_tp1"] = True

                if price <= pos["tp2"]:
                    pos["hit_tp2"] = True

                if price <= pos["tp3"]:
                    pos["hit_tp3"] = True
                    pos["status"] = "CLOSED"
                    changed_positions.append(pos)

        if journal is not None:
            for pos in changed_positions:
                journal.register_trade(
                    trade={
                        "side": pos["side"],
                        "entry": pos["entry"],
                        "stop_loss": pos["stop_loss"],
                        "tp1": pos["tp1"],
                        "tp2": pos["tp2"],
                        "tp3": pos["tp3"],
                    },
                    analysis=analysis,
                    symbol=symbol,
                    metadata={"event": pos["status"], "price": price},
                )

        return changed_positions

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
