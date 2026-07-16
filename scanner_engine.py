"""
scanner_engine.py
Atlas SMC Engine
"""

class ScannerEngine:
    """
    Collects only valid trade setups.
    """

    def __init__(self):
        self.results = []

    def add(self, symbol, trade):

        if not trade.get("valid", False):
            return

        self.results.append({
            "symbol": symbol,
            "direction": trade["direction"],
            "entry": trade["entry"],
            "stop_loss": trade["stop_loss"],
            "tp1": trade["tp1"],
            "tp2": trade["tp2"],
            "tp3": trade["tp3"],
            "rr": trade["rr"]
        })

    def get_results(self):
        return self.results

    def clear(self):
        self.results.clear()
