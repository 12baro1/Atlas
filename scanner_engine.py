"""
scanner_engine.py
Atlas Scanner Engine v2
"""


class ScannerEngine:

    def __init__(self):
        self.trades = []

    def add(self, symbol, result_payload):
        """Canlı engine.analyze() çıktısını tarama kaydına dönüştürür."""
        if result_payload is None:
            return

        analysis = result_payload.get("analysis") or {}
        signal = result_payload.get("signal") or {}
        risk = result_payload.get("risk") or {}
        decision = result_payload.get("decision") or {}
        rr = result_payload.get("rr") or {}

        self.trades.append({
            "symbol": symbol,
            "direction": signal.get("signal"),
            "score": analysis.get("confluence", {}).get("score", 0),
            "grade": analysis.get("setup_quality", {}).get("grade"),
            "stars": analysis.get("setup_quality", {}).get("stars", 0),
            "entry": risk.get("entry"),
            "stop_loss": risk.get("stop_loss"),
            "confidence": signal.get("confidence", 0),
            "decision": decision.get("action"),
            "rr": rr.get("rr"),
            "market_phase": analysis.get("market_phase", {}).get("phase"),
            "setup": analysis.get("setup_quality", {}).get("setup"),
            "reasons": (analysis.get("confluence") or {}).get("reasons", []),
        })

    def results(self):
        return sorted(
            self.trades,
            key=lambda x: x.get("score", 0),
            reverse=True,
        )

    def top(self, limit=20):
        return self.results()[:limit]

    def clear(self):
        self.trades.clear()

    def summary(self):
        if not self.trades:
            return {
                "total": 0,
                "best": None,
                "executable": [],
            }

        ordered = self.results()
        executable = [
            item
            for item in ordered
            if item.get("direction") in ("LONG", "SHORT")
        ]

        return {
            "total": len(self.trades),
            "best": ordered[0],
            "executable": executable[:10],
        }