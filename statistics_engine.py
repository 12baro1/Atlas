"""Runtime signal statistics with finite-number guards."""

import math


class StatisticsEngine:
    def __init__(self):
        self.total = 0
        self.long = 0
        self.short = 0
        self.win = 0
        self.loss = 0
        self.total_rr = 0.0
        self.total_confidence = 0.0

    @staticmethod
    def _number(value):
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return number if math.isfinite(number) else None

    def record(self, trade):
        if not isinstance(trade, dict):
            return

        self.total += 1
        direction = trade.get("direction")
        if direction == "LONG":
            self.long += 1
        elif direction == "SHORT":
            self.short += 1

        payload_rr = trade.get("rr")
        value = payload_rr.get("rr") if isinstance(payload_rr, dict) else payload_rr
        number = self._number(value)
        if number is not None:
            self.total_rr += number

        payload_signal = trade.get("signal")
        confidence = payload_signal.get("confidence") if isinstance(payload_signal, dict) else None
        number = self._number(confidence)
        if number is not None:
            self.total_confidence += number

    def record_payload(self, result_payload):
        """Record an executable directional signal from engine.analyze()."""
        if not isinstance(result_payload, dict):
            return

        signal = result_payload.get("signal") or {}
        if not isinstance(signal, dict):
            return
        direction = signal.get("signal")
        if direction not in ("LONG", "SHORT"):
            return

        self.total += 1
        if direction == "LONG":
            self.long += 1
        else:
            self.short += 1

        rr = result_payload.get("rr") or {}
        value = rr.get("rr") if isinstance(rr, dict) else rr
        number = self._number(value)
        if number is not None:
            self.total_rr += number

        number = self._number(signal.get("confidence"))
        if number is not None:
            self.total_confidence += number

    def record_result(self, win):
        if win:
            self.win += 1
        else:
            self.loss += 1

    def summary(self):
        avg_rr = self.total_rr / self.total if self.total else 0.0
        avg_conf = self.total_confidence / self.total if self.total else 0.0
        finished = self.win + self.loss
        winrate = (self.win / finished) * 100 if finished else 0.0
        return {
            "total_signals": self.total,
            "long_signals": self.long,
            "short_signals": self.short,
            "wins": self.win,
            "losses": self.loss,
            "winrate": round(winrate, 2),
            "average_rr": round(avg_rr, 2),
            "average_confidence": round(avg_conf, 2),
        }

    def reset(self):
        self.__init__()

    def ingest_journal(self, journal_summary):
        """Adapt the TradeJournal aggregate to the legacy statistics shape."""
        if not isinstance(journal_summary, dict) or not journal_summary:
            return self.summary()
        summary = journal_summary.get("summary") or {}
        setup = journal_summary.get("setup_statistics") or {}
        confidence_quality = journal_summary.get("confidence_quality") or {}
        return {
            "total_signals": summary.get("total_trades", 0),
            "long_signals": (setup.get("LONG") or {}).get("total", 0),
            "short_signals": (setup.get("SHORT") or {}).get("total", 0),
            "wins": summary.get("wins", 0),
            "losses": summary.get("losses", 0),
            "winrate": summary.get("winrate", 0),
            "average_rr": summary.get("average_r", 0),
            "average_confidence": confidence_quality.get("calibration_gap", 0),
        }
