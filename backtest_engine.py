"""
backtest_engine.py
Atlas Backtest Engine v4
"""

class BacktestEngine:

    def __init__(self):

        self.total = 0
        self.wins = 0
        self.losses = 0

        self.tp1 = 0
        self.tp2 = 0
        self.tp3 = 0

        self.net_rr = 0.0
        self.gross_profit_rr = 0.0
        self.gross_loss_rr = 0.0

        self.history = []

    def record(self, trade):

        self.total += 1

        result = trade.get("result", "LOSS")

        rr = abs(trade.get("rr", 0))
        signed_rr = rr if result == "WIN" else -rr

        self.net_rr += signed_rr

        if result == "WIN":

            self.wins += 1
            self.gross_profit_rr += rr

        else:

            self.losses += 1
            self.gross_loss_rr += rr

        if trade.get("tp") == 1:
            self.tp1 += 1

        elif trade.get("tp") == 2:
            self.tp2 += 1

        elif trade.get("tp") == 3:
            self.tp3 += 1

        self.history.append(trade)

    def statistics(self):

        if self.total == 0:

            return {
                "total": 0,
                "wins": 0,
                "losses": 0,
                "winrate": 0,
                "avg_rr": 0,
                "expectancy": 0,
                "profit_factor": 0,
                "tp1": 0,
                "tp2": 0,
                "tp3": 0
            }

        gross_loss_rr = self.gross_loss_rr if self.gross_loss_rr > 0 else 0.0
        profit_factor = self.gross_profit_rr / gross_loss_rr if gross_loss_rr > 0 else self.gross_profit_rr
        expectancy = self.net_rr / self.total

        return {

            "total": self.total,

            "wins": self.wins,

            "losses": self.losses,

            "winrate": round(
                (self.wins / self.total) * 100,
                2
            ),

            "avg_rr": round(
                self.net_rr / self.total,
                2
            ),

            "expectancy": round(expectancy, 2),

            "profit_factor": round(profit_factor, 2),

            "tp1": self.tp1,

            "tp2": self.tp2,

            "tp3": self.tp3

        }

    def reset(self):

        self.__init__()
