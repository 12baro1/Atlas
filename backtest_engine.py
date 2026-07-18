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

    def monte_carlo(self, iterations=1000, sample_size=None):
        """Geçmiş RR dağılımına göre Monte Carlo simülasyonu üretir."""
        if not self.history:
            return {
                "iterations": 0,
                "sample_size": 0,
                "expected_rr": 0,
                "worst_case_rr": 0,
                "best_case_rr": 0,
            }

        outcomes = [abs(trade.get("rr", 0)) if trade.get("result") == "WIN" else -abs(trade.get("rr", 0)) for trade in self.history]
        sample_size = sample_size or min(20, len(outcomes))
        sample_size = max(1, min(sample_size, len(outcomes)))

        simulations = []
        for index in range(min(iterations, 5000)):
            start = (index * sample_size) % len(outcomes)
            sample = outcomes[start:start + sample_size]
            if len(sample) < sample_size:
                sample = sample + outcomes[: sample_size - len(sample)]
            simulations.append(sum(sample))

        return {
            "iterations": len(simulations),
            "sample_size": sample_size,
            "expected_rr": round(sum(simulations) / len(simulations), 2),
            "worst_case_rr": round(min(simulations), 2),
            "best_case_rr": round(max(simulations), 2),
        }

    def walk_forward(self, window=20, step=10):
        """Kaydırmalı pencere ile walk-forward performansı hesaplar."""
        if not self.history:
            return {"windows": [], "average_rr": 0, "average_winrate": 0}

        window = max(5, window)
        step = max(1, step)
        windows = []

        for start in range(0, len(self.history) - window + 1, step):
            chunk = self.history[start:start + window]
            stats = self._chunk_stats(chunk)
            stats["start"] = start
            stats["end"] = start + window
            windows.append(stats)

        if not windows:
            windows = [self._chunk_stats(self.history)]

        average_rr = sum(item["avg_rr"] for item in windows) / len(windows)
        average_winrate = sum(item["winrate"] for item in windows) / len(windows)

        return {
            "windows": windows,
            "average_rr": round(average_rr, 2),
            "average_winrate": round(average_winrate, 2),
        }

    def trade_analytics(self):
        """Trade geçmişinden kalite ve dağılım analitiği üretir."""
        if not self.history:
            return {
                "total": 0,
                "long_trades": 0,
                "short_trades": 0,
                "winrate": 0,
                "avg_rr": 0,
                "median_rr": 0,
                "expectancy": 0,
            }

        rr_values = [abs(trade.get("rr", 0)) if trade.get("result") == "WIN" else -abs(trade.get("rr", 0)) for trade in self.history]
        long_trades = len([trade for trade in self.history if trade.get("side") == "LONG"])
        short_trades = len([trade for trade in self.history if trade.get("side") == "SHORT"])
        ordered_rr = sorted(rr_values)
        middle = len(ordered_rr) // 2
        if len(ordered_rr) % 2 == 0:
            median_rr = (ordered_rr[middle - 1] + ordered_rr[middle]) / 2
        else:
            median_rr = ordered_rr[middle]

        stats = self.statistics()
        return {
            "total": len(self.history),
            "long_trades": long_trades,
            "short_trades": short_trades,
            "winrate": stats["winrate"],
            "avg_rr": stats["avg_rr"],
            "median_rr": round(median_rr, 2),
            "expectancy": stats["expectancy"],
            "profit_factor": stats["profit_factor"],
        }

    def _chunk_stats(self, chunk):
        total = len(chunk)
        wins = len([trade for trade in chunk if trade.get("result") == "WIN"])
        losses = total - wins
        rr_values = [abs(trade.get("rr", 0)) if trade.get("result") == "WIN" else -abs(trade.get("rr", 0)) for trade in chunk]
        avg_rr = sum(rr_values) / total if total else 0
        winrate = (wins / total) * 100 if total else 0
        return {
            "total": total,
            "wins": wins,
            "losses": losses,
            "winrate": round(winrate, 2),
            "avg_rr": round(avg_rr, 2),
        }

    def ingest_journal(self, journal_summary):
        """Trade Journal performans raporunu backtest görünümüne dönüştürür."""
        if not journal_summary:
            return self.statistics()

        summary = journal_summary.get("summary", {})
        return {
            "total": summary.get("total_trades", 0),
            "wins": summary.get("wins", 0),
            "losses": summary.get("losses", 0),
            "winrate": summary.get("winrate", 0),
            "avg_rr": summary.get("average_r", 0),
            "expectancy": summary.get("expectancy", 0),
            "profit_factor": summary.get("profit_factor", 0),
            "tp1": summary.get("tp_sl_analysis", {}).get("tp1_hit_rate", 0),
            "tp2": summary.get("tp_sl_analysis", {}).get("tp2_hit_rate", 0),
            "tp3": summary.get("tp_sl_analysis", {}).get("tp3_hit_rate", 0),
        }
