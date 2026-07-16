"""
statistics_engine.py
Atlas SMC Engine
"""

class StatisticsEngine:
    """
    Tracks strategy statistics.
    """

    def __init__(self):
        self.total = 0
        self.wins = 0
        self.losses = 0
        self.total_rr = 0.0
        self.best_win_streak = 0
        self.current_win_streak = 0

    def add_trade(self, result, rr=0.0):

        self.total += 1

        if result == "WIN":
            self.wins += 1
            self.current_win_streak += 1
            self.best_win_streak = max(
                self.best_win_streak,
                self.current_win_streak
            )
        else:
            self.losses += 1
            self.current_win_streak = 0

        self.total_rr += rr

    def summary(self):

        win_rate = 0

        if self.total:
            win_rate = (self.wins / self.total) * 100

        average_rr = 0

        if self.total:
            average_rr = self.total_rr / self.total

        return {
            "total": self.total,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(win_rate, 2),
            "average_rr": round(average_rr, 2),
            "best_win_streak": self.best_win_streak
        }

    def reset(self):
        self.__init__()
