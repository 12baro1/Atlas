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
            "entry_type": (analysis.get("entry") or {}).get("entry_type", "NONE"),
            "stop_loss": risk.get("stop_loss"),
            "tp1": risk.get("tp1"),
            "tp2": risk.get("tp2"),
            "tp3": risk.get("tp3"),
            "confidence": signal.get("confidence", 0),
            "decision": decision.get("action"),
            "tradable": (
                signal.get("signal") in ("LONG", "SHORT")
                and decision.get("action") in ("EXECUTE", "EXECUTE_WITH_CAUTION")
                and (risk.get("risk_setup_valid") is not False)
                and all(risk.get(key) is not None for key in ("stop_loss", "tp1", "tp2", "tp3"))
            ),
            "rr": rr.get("rr"),
            "market_phase": analysis.get("market_phase", {}).get("phase"),
            "setup": analysis.get("setup_quality", {}).get("setup"),
            "reasons": (analysis.get("confluence") or {}).get("reasons", []),
        })

    def results(self):
        return sorted(
            self.trades,
            key=lambda x: (
                bool(x.get("tradable")),
                float(x.get("rr") or 0),
                float(x.get("score") or 0),
            ),
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
        executable = [item for item in ordered if item.get("tradable") is True]

        return {
            "total": len(self.trades),
            "best": ordered[0],
            "executable": executable[:10],
        }