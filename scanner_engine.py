"""
scanner_engine.py
Atlas SMC Engine v2
"""

class ScannerEngine:

    def __init__(self):
        self.trades = []

    def add(self, symbol, trade):

        if trade is None:
            return

        self.trades.append({
            "symbol": symbol,
            "direction": trade["direction"],
            "score": trade["score"],
            "grade": trade["grade"],
            "stars": trade["stars"],
            "entry": trade["entry"],
            "confirmation": trade["confirmation"],
            "risk": trade["risk"],
            "reasons": trade["reasons"]
        })

    def results(self):

        return sorted(
            self.trades,
            key=lambda x: x["score"],
            reverse=True
        )

    def top(self, limit=20):

        return self.results()[:limit]

    def clear(self):

        self.trades.clear()

    def summary(self):

        if len(self.trades) == 0:
            return {
                "total": 0,
                "best": None
            }

        ordered = self.results()

        return {
            "total": len(self.trades),
            "best": ordered[0]
        }
