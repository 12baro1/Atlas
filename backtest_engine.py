"""
backtest_engine.py
Atlas SMC Engine
"""

class BacktestEngine:
    """
    Simple strategy performance tracker.
    """

    def __init__(self):
        self.trades = []

    def add_trade(self, trade):

        if not trade:
            return

        self.trades.append(trade)

    def summary(self):

        total = len(self.trades)

        wins = sum(1 for t in self.trades if t.get("result") == "WIN")
        losses = sum(1 for t in self.trades if t.get("result") == "LOSS")

        win_rate = (wins / total * 100) if total else 0

        total_rr = sum(t.get("rr", 0) for t in self.trades)

        return {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 2),
            "total_rr": round(total_rr, 2)
        }

    def clear(self):
        self.trades.clear()
