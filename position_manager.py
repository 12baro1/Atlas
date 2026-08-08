"""
position_manager.py
Atlas SMC Engine v2
"""

class PositionManager:

    def __init__(self):

        self.positions = []

    def open(self, symbol, trade):
        return self.open_with_journal(symbol, trade)

    def open_with_journal(self, symbol, trade, journal=None, analysis=None):

        if trade is None:
            return

        # trade_manager.build() iç içe (entry=dict, risk=dict) üretir;
        # flat kayıtlar da olabilir. İkisini de tüket:
        entry_record = trade.get("entry")
        if isinstance(entry_record, dict):
            entry_price = entry_record.get("entry")
            stop_loss = entry_record.get("stop_loss")
            risk_record = trade.get("risk") or {}
            tp1, tp2, tp3 = risk_record.get("tp1"), risk_record.get("tp2"), risk_record.get("tp3")
        else:
            entry_price = entry_record
            stop_loss = trade.get("stop_loss")
            tp1, tp2, tp3 = trade.get("tp1"), trade.get("tp2"), trade.get("tp3")

        position = {
            "symbol": symbol,
            "side": trade.get("side") or trade.get("direction"),
            "entry": entry_price,
            "stop_loss": stop_loss,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "status": "OPEN",
            "remaining_percent": 100,
            "realized_percent": 0,
            "sl_moved_to_entry": False,
            "runner_active": False,
            "hit_tp1": False,
            "hit_tp2": False,
            "hit_tp3": False
        }

        self.positions.append(position)

        if journal is not None:
            journal.register_trade(
                trade=trade,
                analysis=analysis,
                symbol=symbol,
                metadata={"event": "OPEN"},
            )

        return position

    def update(self, symbol, price):
        return self.update_with_journal(symbol, price)

    def update_with_journal(self, symbol, price, journal=None, analysis=None):

        changed_positions = []

        for pos in self.positions:

            if pos["symbol"] != symbol:
                continue

            if pos["status"] != "OPEN":
                continue

            if pos["side"] == "LONG":

                if price <= pos["stop_loss"]:
                    pos["status"] = "STOP"
                    changed_positions.append(pos)

                if price >= pos["tp1"] and not pos["hit_tp1"]:
                    self._take_partial(pos, percent=30)
                    pos["hit_tp1"] = True
                    pos["stop_loss"] = pos["entry"]
                    pos["sl_moved_to_entry"] = True
                    changed_positions.append(dict(pos, event="TP1", partial_percent=30))

                if price >= pos["tp2"] and not pos["hit_tp2"]:
                    self._take_partial(pos, percent=30)
                    pos["hit_tp2"] = True
                    pos["runner_active"] = True
                    changed_positions.append(dict(pos, event="TP2", partial_percent=30))

                if price >= pos["tp3"] and not pos["hit_tp3"]:
                    self._take_partial(pos, percent=40)
                    pos["hit_tp3"] = True
                    pos["status"] = "CLOSED"
                    changed_positions.append(dict(pos, event="TP3", partial_percent=40))

            else:

                if price >= pos["stop_loss"]:
                    pos["status"] = "STOP"
                    changed_positions.append(pos)

                if price <= pos["tp1"] and not pos["hit_tp1"]:
                    self._take_partial(pos, percent=30)
                    pos["hit_tp1"] = True
                    pos["stop_loss"] = pos["entry"]
                    pos["sl_moved_to_entry"] = True
                    changed_positions.append(dict(pos, event="TP1", partial_percent=30))

                if price <= pos["tp2"] and not pos["hit_tp2"]:
                    self._take_partial(pos, percent=30)
                    pos["hit_tp2"] = True
                    pos["runner_active"] = True
                    changed_positions.append(dict(pos, event="TP2", partial_percent=30))

                if price <= pos["tp3"] and not pos["hit_tp3"]:
                    self._take_partial(pos, percent=40)
                    pos["hit_tp3"] = True
                    pos["status"] = "CLOSED"
                    changed_positions.append(dict(pos, event="TP3", partial_percent=40))

        if journal is not None:
            for pos in changed_positions:
                journal.register_trade(
                    trade={
                        "side": pos["side"],
                        "entry": pos["entry"],
                        "stop_loss": pos["stop_loss"],
                        "tp1": pos["tp1"],
                        "tp2": pos["tp2"],
                        "tp3": pos["tp3"],
                    },
                    analysis=analysis,
                    symbol=symbol,
                    metadata={"event": pos.get("event") or pos["status"], "price": price},
                )

        return changed_positions

    def manage_runner(self, symbol, price, trend_direction=None, trail_distance=None):
        """Manage remaining runner after TP2 with optional trend-aware trailing stop."""
        updates = []
        for pos in self.positions:
            if pos.get("symbol") != symbol or pos.get("status") != "OPEN" or not pos.get("runner_active"):
                continue
            if trail_distance and trail_distance > 0:
                if pos["side"] == "LONG" and trend_direction in [None, "LONG", "BULLISH"]:
                    pos["stop_loss"] = max(pos["stop_loss"], price - trail_distance)
                elif pos["side"] == "SHORT" and trend_direction in [None, "SHORT", "BEARISH"]:
                    pos["stop_loss"] = min(pos["stop_loss"], price + trail_distance)
            updates.append(pos)
        return updates

    def _take_partial(self, pos, percent):
        available = max(0, pos.get("remaining_percent", 100))
        taken = min(percent, available)
        pos["remaining_percent"] = available - taken
        pos["realized_percent"] = pos.get("realized_percent", 0) + taken

    def open_positions(self):

        return [
            p for p in self.positions
            if p["status"] == "OPEN"
        ]

    def closed_positions(self):

        return [
            p for p in self.positions
            if p["status"] != "OPEN"
        ]

    def reset(self):

        self.positions.clear()
