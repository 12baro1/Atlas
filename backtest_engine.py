"""
backtest_engine.py
Atlas Backtest Engine v4
"""

class BacktestEngine:

    def __init__(self):

        self.total = 0
        self.pending = 0
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

        if trade is None:
            return

        # Live analysis payloads have no realized outcome yet. Keep them
        # visible as pending records, but never include them in closed-trade
        # win rate, expectancy, or profit-factor denominators.
        if "signal" in trade and "rr" in trade and "risk" in trade:
            self._record_payload(trade)
            return

        result = str(trade.get("result", "") or "").upper()
        if result not in {"WIN", "LOSS"}:
            self.pending += 1
            self.history.append(dict(trade, result="PENDING"))
            return

        self.total += 1
        signed_rr = self._signed_trade_rr(trade)
        rr = abs(signed_rr)
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

    @staticmethod
    def _signed_trade_rr(trade):
        """Prefer realized net R from simulations/journals; fall back to result + RR."""
        for key in ("net_rr", "pnl_rr"):
            value = trade.get(key)
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                return float(value)
        value = trade.get("rr", 0)
        try:
            value = abs(float(value or 0))
        except (TypeError, ValueError, OverflowError):
            value = 0.0
        return value if str(trade.get("result", "")).upper() == "WIN" else -value

    def _record_payload(self, result_payload):
        """Canlı engine.analyze() çıktısını geri test kaydına işler."""
        signal = result_payload.get("signal") or {}
        risk = result_payload.get("risk") or {}
        rr = result_payload.get("rr") or {}

        entry = {"signal": signal, "risk": risk, "rr": rr, "result": "PENDING"}
        self.pending += 1
        if signal.get("signal") == "LONG":
            entry["side"] = "LONG"
        elif signal.get("signal") == "SHORT":
            entry["side"] = "SHORT"
        entry["confidence"] = signal.get("confidence")
        entry["tp"] = (risk.get("dynamic_tp") or {}).get("tp_target")

        self.history.append(entry)

    @staticmethod
    def simulate_trade(entry, stop_loss, targets, candles, side="LONG",
                       partial_weights=None, round_trip_cost_rate=0.002):
        """Conservative OHLC simulation with partial TP exits and net-R costs.

        If SL and the next TP are both inside one candle, SL is assumed first.
        At most one new TP can fill per candle because intrabar ordering is unknown.
        """
        try:
            entry = float(entry)
            stop_loss = float(stop_loss)
            side = str(side or "").upper()
            if not math.isfinite(entry) or not math.isfinite(stop_loss) or entry <= 0:
                raise ValueError
            if side not in ("LONG", "SHORT"):
                raise ValueError
            risk = abs(entry - stop_loss)
            if risk <= 0 or (side == "LONG" and stop_loss >= entry) or (side == "SHORT" and stop_loss <= entry):
                raise ValueError
            levels = [float(value) for value in (targets or []) if value is not None]
            levels = [value for value in levels if math.isfinite(value)]
            if not levels:
                raise ValueError
            if any((value <= entry if side == "LONG" else value >= entry) for value in levels):
                raise ValueError
            if any((levels[i] >= levels[i + 1] if side == "LONG" else levels[i] <= levels[i + 1])
                   for i in range(len(levels) - 1)):
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            return {"result": "INVALID", "reason": "invalid_trade_geometry"}

        if partial_weights is None:
            weights = [1.0 / len(levels)] * len(levels)
        else:
            try:
                weights = [max(0.0, float(value)) for value in partial_weights[:len(levels)]]
            except (TypeError, ValueError, OverflowError):
                return {"result": "INVALID", "reason": "invalid_partial_weights"}
            weights += [0.0] * (len(levels) - len(weights))
            total_weight = sum(weights)
            if total_weight <= 0 or not math.isfinite(total_weight):
                return {"result": "INVALID", "reason": "invalid_partial_weights"}
            weights = [value / total_weight for value in weights]

        remaining = 1.0
        realized_rr = 0.0
        targets_hit = 0
        for candle in candles or []:
            try:
                high = float(candle.get("high") if isinstance(candle, dict) else candle.high)
                low = float(candle.get("low") if isinstance(candle, dict) else candle.low)
            except (TypeError, ValueError, AttributeError, OverflowError):
                continue
            if not (math.isfinite(high) and math.isfinite(low)):
                continue
            stop_hit = low <= stop_loss if side == "LONG" else high >= stop_loss
            next_target_hit = (
                high >= levels[targets_hit] if side == "LONG"
                else low <= levels[targets_hit]
            ) if targets_hit < len(levels) else False

            # Unknown intrabar order: stop takes precedence over a target.
            if stop_hit:
                realized_rr -= remaining
                remaining = 0.0
                cost_rr = (abs(entry) * max(0.0, float(round_trip_cost_rate))) / risk
                net_rr = realized_rr - cost_rr
                return {
                    "result": "WIN" if net_rr > 0 else "LOSS",
                    "gross_rr": round(realized_rr, 4),
                    "net_rr": round(net_rr, 4),
                    "targets_hit": targets_hit,
                    "remaining_fraction": 0.0,
                    "close_reason": "stop_after_partial_tp" if targets_hit else "stop_loss",
                    "intrabar_policy": "stop_first",
                }
            if next_target_hit:
                weight = weights[targets_hit]
                target_rr = abs(levels[targets_hit] - entry) / risk
                realized_rr += weight * target_rr
                remaining -= weight
                targets_hit += 1
                if remaining <= 1e-9:
                    cost_rr = (abs(entry) * max(0.0, float(round_trip_cost_rate))) / risk
                    net_rr = realized_rr - cost_rr
                    return {
                        "result": "WIN" if net_rr > 0 else "LOSS",
                        "gross_rr": round(realized_rr, 4),
                        "net_rr": round(net_rr, 4),
                        "targets_hit": targets_hit,
                        "remaining_fraction": 0.0,
                        "close_reason": "all_targets_hit",
                        "intrabar_policy": "one_target_per_candle",
                    }

        cost_rr = (abs(entry) * max(0.0, float(round_trip_cost_rate))) / risk
        return {
            "result": "PENDING",
            "gross_rr": round(realized_rr, 4),
            "net_rr": round(realized_rr - cost_rr, 4),
            "targets_hit": targets_hit,
            "remaining_fraction": round(remaining, 6),
            "close_reason": "history_exhausted",
            "intrabar_policy": "stop_first_one_target_per_candle",
        }

    def performance_gate(self, minimum_trades=200, minimum_profit_factor=1.5,
                         maximum_drawdown_pct=10.0, risk_percent=1.0):
        """Return a validation gate; never treat a small sample as proven edge."""
        closed = self._closed_history()
        stats = self.statistics()
        equity = peak = 100.0
        max_drawdown = 0.0
        risk_fraction = max(0.0, float(risk_percent)) / 100.0
        for trade in closed:
            signed_rr = self._signed_trade_rr(trade)
            equity *= max(0.0, 1.0 + signed_rr * risk_fraction)
            peak = max(peak, equity)
            if peak > 0:
                max_drawdown = max(max_drawdown, (peak - equity) / peak * 100.0)
        enough_data = len(closed) >= int(minimum_trades)
        pf_ok = stats["profit_factor"] >= float(minimum_profit_factor)
        dd_ok = max_drawdown <= float(maximum_drawdown_pct)
        return {
            "ready": bool(enough_data and pf_ok and dd_ok),
            "sample_sufficient": enough_data,
            "closed_trades": len(closed),
            "minimum_trades": int(minimum_trades),
            "profit_factor": stats["profit_factor"],
            "minimum_profit_factor": float(minimum_profit_factor),
            "max_drawdown_pct": round(max_drawdown, 2),
            "maximum_drawdown_pct": float(maximum_drawdown_pct),
            "risk_percent_per_trade": float(risk_percent),
            "checks": {"sample": enough_data, "profit_factor": pf_ok, "drawdown": dd_ok},
        }

    def statistics(self):

        if self.total == 0:

            return {
                "total": 0,
                "pending": self.pending,
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

            "pending": self.pending,

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

        closed = self._closed_history()
        if not closed:
            return {
                "iterations": 0,
                "sample_size": 0,
                "expected_rr": 0,
                "worst_case_rr": 0,
                "best_case_rr": 0,
            }
        outcomes = [self._signed_trade_rr(trade) for trade in closed]
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
        closed = self._closed_history()
        if not closed:
            return {"windows": [], "average_rr": 0, "average_winrate": 0}

        window = max(5, window)
        step = max(1, step)
        windows = []

        for start in range(0, len(closed) - window + 1, step):
            chunk = closed[start:start + window]
            stats = self._chunk_stats(chunk)
            stats["start"] = start
            stats["end"] = start + window
            windows.append(stats)

        if not windows:
            windows = [self._chunk_stats(closed)]

        average_rr = sum(item["avg_rr"] for item in windows) / len(windows)
        average_winrate = sum(item["winrate"] for item in windows) / len(windows)

        return {
            "windows": windows,
            "average_rr": round(average_rr, 2),
            "average_winrate": round(average_winrate, 2),
        }

    def trade_analytics(self):
        """Trade geçmişinden kalite ve dağılım analitiği üretir."""
        closed = self._closed_history()
        if not closed:
            return {
                "total": 0,
                "pending": self.pending,
                "long_trades": 0,
                "short_trades": 0,
                "winrate": 0,
                "avg_rr": 0,
                "median_rr": 0,
                "expectancy": 0,
            }

        rr_values = [self._signed_trade_rr(trade) for trade in closed]
        long_trades = len([trade for trade in closed if trade.get("side") == "LONG"])
        short_trades = len([trade for trade in closed if trade.get("side") == "SHORT"])
        ordered_rr = sorted(rr_values)
        middle = len(ordered_rr) // 2
        if len(ordered_rr) % 2 == 0:
            median_rr = (ordered_rr[middle - 1] + ordered_rr[middle]) / 2
        else:
            median_rr = ordered_rr[middle]

        stats = self.statistics()
        return {
            "total": len(closed),
            "pending": self.pending,
            "long_trades": long_trades,
            "short_trades": short_trades,
            "winrate": stats["winrate"],
            "avg_rr": stats["avg_rr"],
            "median_rr": round(median_rr, 2),
            "expectancy": stats["expectancy"],
            "profit_factor": stats["profit_factor"],
            "performance_gate": self.performance_gate(),
            "direction_breakdown": {
                side: self._chunk_stats([trade for trade in closed if str(trade.get("side", "")).upper() == side])
                for side in ("LONG", "SHORT")
            },
        }

    def _closed_history(self):
        """Return only trades with a realized WIN/LOSS outcome."""
        return [
            trade for trade in self.history
            if str(trade.get("result", "")).upper() in {"WIN", "LOSS"}
        ]

    def _chunk_stats(self, chunk):
        total = len(chunk)
        wins = len([trade for trade in chunk if trade.get("result") == "WIN"])
        losses = total - wins
        rr_values = [self._signed_trade_rr(trade) for trade in chunk]
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
