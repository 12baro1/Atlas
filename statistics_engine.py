"""
statistics_engine.py
Atlas SMC Engine v2
"""

class StatisticsEngine:

    def __init__(self):

        self.total = 0

        self.long = 0
        self.short = 0

        self.win = 0
        self.loss = 0

        self.total_rr = 0

        self.total_confidence = 0

    def record(self, trade):

        if trade is None:
            return

        self.total += 1

        if trade["direction"] == "LONG":
            self.long += 1

        elif trade["direction"] == "SHORT":
            self.short += 1

        if trade.get("rr"):

            self.total_rr += trade["rr"]["rr"]

        if trade.get("signal"):

            self.total_confidence += trade["signal"]["confidence"]

    def record_result(self, win):

        if win:
            self.win += 1
        else:
            self.loss += 1

    def summary(self):

        if self.total == 0:

            avg_rr = 0
            avg_conf = 0

        else:

            avg_rr = self.total_rr / self.total
            avg_conf = self.total_confidence / self.total

        total_finished = self.win + self.loss

        if total_finished == 0:
            winrate = 0
        else:
            winrate = (self.win / total_finished) * 100

        return {

            "total_signals": self.total,

            "long_signals": self.long,

            "short_signals": self.short,

            "wins": self.win,

            "losses": self.loss,

            "winrate": round(winrate,2),

            "average_rr": round(avg_rr,2),

            "average_confidence": round(avg_conf,2)

        }

    def reset(self):

        self.__init__()
    
