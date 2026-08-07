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

        if trade.get("direction") == "LONG":
            self.long += 1

        elif trade.get("direction") == "SHORT":
            self.short += 1

        if trade.get("rr"):
            payload_rr = trade["rr"]
            value = payload_rr.get("rr") if isinstance(payload_rr, dict) else payload_rr
            if isinstance(value, (int, float)):
                self.total_rr += value

        if trade.get("signal"):
            payload_signal = trade["signal"]
            confidence = payload_signal.get("confidence") if isinstance(payload_signal, dict) else payload_signal
            if isinstance(confidence, (int, float)):
                self.total_confidence += confidence

    def record_payload(self, result_payload):
        """Canlı engine.analyze() çıktısını istatistiklere işler."""
        if result_payload is None:
            return

        signal = result_payload.get("signal") or {}
        risk = result_payload.get("risk") or {}
        rr = result_payload.get("rr") or {}

        direction = signal.get("signal")
        if direction not in ("LONG", "SHORT"):
            return

        self.total += 1
        if direction == "LONG":
            self.long += 1
        else:
            self.short += 1

        value = rr.get("rr") if isinstance(rr, dict) else rr
        if isinstance(value, (int, float)):
            self.total_rr += value

        confidence = signal.get("confidence")
        if isinstance(confidence, (int, float)):
            self.total_confidence += confidence

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

    def ingest_journal(self, journal_summary):
        """Trade Journal çıktısını StatisticsEngine formatına dönüştürür."""
        if not journal_summary:
            return self.summary()

        return {
            "total_signals": journal_summary.get("summary", {}).get("total_trades", 0),
            "long_signals": journal_summary.get("setup_statistics", {}).get("LONG", {}).get("total", 0),
            "short_signals": journal_summary.get("setup_statistics", {}).get("SHORT", {}).get("total", 0),
            "wins": journal_summary.get("summary", {}).get("wins", 0),
            "losses": journal_summary.get("summary", {}).get("losses", 0),
            "winrate": journal_summary.get("summary", {}).get("winrate", 0),
            "average_rr": journal_summary.get("summary", {}).get("average_r", 0),
            "average_confidence": journal_summary.get("confidence_quality", {}).get("calibration_gap", 0),
        }
    
