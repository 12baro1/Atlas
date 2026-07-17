"""
backtest_engine.py
Atlas SMC Engine v2
"""

class BacktestEngine:

    def __init__(self):

        self.trades = []

    def record(self, symbol, trade, result):

        if trade is None:
            return

        self.trades.append({

            "symbol": symbol,

            "direction": trade["direction"],

            "entry": trade["entry"],

            "stop_loss": trade["stop_loss"],

            "tp1": trade["tp1"],

            "tp2": trade["tp2"],

            "tp3": trade["tp3"],

            "rr": trade["rr"],

            "result": result

        })

    def summary(self):

        total = len(self.trades)

        if total == 0:

            return {
                "total": 0,
                "wins": 0,
                "losses": 0,
                "winrate": 0,
                "average_rr": 0,
                "profit_factor": 0
            }

        wins = 0
        losses = 0

        rr_sum = 0

        gross_profit = 0
        gross_loss = 0

        for trade in self.trades:

            rr_sum += trade["rr"]

            if trade["result"] == "WIN":

                wins += 1
                gross_profit += trade["rr"]

            else:

                losses += 1
                gross_loss += 1

        winrate = (wins / total) * 100

        average_rr = rr_sum / total

        if gross_loss == 0:
            profit_factor = gross_profit
        else:
            profit_factor = gross_profit / gross_loss

        return {

            "total": total,

            "wins": wins,

            "losses": losses,

            "winrate": round(winrate,2),

            "average_rr": round(average_rr,2),

            "profit_factor": round(profit_factor,2)

        }

    def reset(self):

        self.trades.clear()
