"""
trade_journal.py
Atlas Trade Journal & Performance Analytics Engine
"""

from __future__ import annotations

import copy
import json
import math
import sqlite3
import statistics
import time
import uuid
from collections import defaultdict
from pathlib import Path


class TradeJournal:
    """Atlas analiz, trade ve performans kayıtlarını tek bir yerde toplar."""

    def __init__(self, db_path=None):
        self.db_path = str(db_path) if db_path else None
        self._snapshots = []
        self._trades = []
        self._engine_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "total": 0})
        self._ensure_store()

    def record_analysis(self, analysis, symbol=None, timeframe="multi", timestamp=None, metadata=None):
        """İşlem açılışındaki tüm analiz çıktısını snapshot olarak kaydeder."""
        snapshot = {
            "id": self._uuid("snapshot"),
            "timestamp": int(timestamp or time.time() * 1000),
            "symbol": symbol or analysis.get("symbol", "UNKNOWN"),
            "timeframe": timeframe,
            "decision": copy.deepcopy(analysis.get("decision") or {}),
            "signal": copy.deepcopy(analysis.get("signal") or {}),
            "confluence": copy.deepcopy(analysis.get("confluence") or {}),
            "risk": copy.deepcopy(analysis.get("risk") or {}),
            "entry": copy.deepcopy(analysis.get("entry") or {}),
            "market_phase": copy.deepcopy(analysis.get("market_phase") or {}),
            "session": self._extract_session(analysis),
            "killzone": self._extract_killzone(analysis),
            "modules": copy.deepcopy(analysis.get("modules") or {}),
            "structure": self._compact_structure(analysis),
            "metadata": copy.deepcopy(metadata or {}),
        }

        self._snapshots.append(snapshot)
        self._persist_snapshot(snapshot)
        return snapshot

    def register_trade(self, trade, analysis=None, symbol=None, timestamp=None, metadata=None):
        """Açılan işlemi trade journal'a yazar."""
        now = int(timestamp or time.time() * 1000)
        snapshot = self._latest_snapshot(symbol=symbol)

        record = {
            "id": self._uuid("trade"),
            "symbol": symbol or trade.get("symbol") or (analysis or {}).get("symbol", "UNKNOWN"),
            "side": trade.get("side") or trade.get("direction", "NONE"),
            "status": "OPEN",
            "opened_at": now,
            "closed_at": None,
            "entry": trade.get("entry"),
            "stop_loss": trade.get("stop_loss"),
            "take_profit": trade.get("tp3") or trade.get("take_profit"),
            "tp1": trade.get("tp1"),
            "tp2": trade.get("tp2"),
            "tp3": trade.get("tp3"),
            "result": None,
            "rr": trade.get("rr"),
            "pnl_rr": None,
            "hold_seconds": None,
            "confidence": self._value_from(trade, "confidence", default=self._snapshot_value(snapshot, "signal", "confidence")),
            "confluence_score": self._value_from(trade, "confluence_score", default=self._snapshot_value(snapshot, "confluence", "score")),
            "market_phase": self._snapshot_value(snapshot, "market_phase", "phase") or trade.get("market_phase", "UNKNOWN"),
            "session": self._snapshot_value(snapshot, "session", "session") or trade.get("session", "UNKNOWN"),
            "killzone": self._snapshot_value(snapshot, "killzone", "name") or trade.get("killzone", "UNKNOWN"),
            "analysis_snapshot_id": snapshot["id"] if snapshot else None,
            "analysis": copy.deepcopy(analysis or {}),
            "metadata": copy.deepcopy(metadata or {}),
            "closed_payload": None,
        }

        self._trades.append(record)
        self._persist_trade(record)
        return record

    def close_trade(self, trade_id, exit_price, result=None, timestamp=None, reason=None, exit_metadata=None):
        """Açık trade'i kapatır ve sonuç metriklerini hesaplar."""
        trade = self._find_trade(trade_id)
        if trade is None:
            return None

        closed_at = int(timestamp or time.time() * 1000)
        result = result or self._infer_result(trade, exit_price)
        pnl_rr = self._calculate_trade_rr(trade, exit_price, result)

        trade["status"] = "CLOSED"
        trade["closed_at"] = closed_at
        trade["exit_price"] = exit_price
        trade["result"] = result
        trade["pnl_rr"] = pnl_rr
        trade["hold_seconds"] = max(0.0, (closed_at - trade["opened_at"]) / 1000.0)
        trade["close_reason"] = reason
        trade["closed_payload"] = copy.deepcopy(exit_metadata or {})

        self._persist_trade(trade)
        self._update_engine_stats(trade)
        return trade

    def summary(self):
        """Trade geçmişinden ana performans özetini üretir."""
        closed_trades = [trade for trade in self._trades if trade.get("status") == "CLOSED"]
        if not closed_trades:
            return self._empty_summary()

        metrics = self._metrics(closed_trades)
        strengths = self.strength_report()
        weaknesses = self.weakness_report()
        return {
            "total_trades": len(closed_trades),
            "open_trades": len([trade for trade in self._trades if trade.get("status") == "OPEN"]),
            "wins": len([trade for trade in closed_trades if trade.get("result") == "WIN"]),
            "losses": len([trade for trade in closed_trades if trade.get("result") == "LOSS"]),
            "winrate": metrics["winrate"],
            "expectancy": metrics["expectancy"],
            "profit_factor": metrics["profit_factor"],
            "average_r": metrics["average_r"],
            "max_drawdown": metrics["max_drawdown"],
            "sharpe_like": metrics["sharpe_like"],
            "average_hold_seconds": metrics["average_hold_seconds"],
            "best_streak": metrics["best_streak"],
            "worst_streak": metrics["worst_streak"],
            "session_statistics": self.session_statistics(),
            "killzone_statistics": self.killzone_statistics(),
            "coin_statistics": self.coin_statistics(),
            "timeframe_statistics": self.timeframe_statistics(),
            "market_phase_statistics": self.market_phase_statistics(),
            "setup_statistics": self.setup_statistics(),
            "engine_statistics": self.engine_statistics(),
            "confidence_quality": self.confidence_quality(),
            "confluence_quality": self.confluence_quality(),
            "risk_quality": self.risk_quality(),
            "tp_sl_analysis": self.tp_sl_analysis(),
            "performance_trend": self.performance_trend(),
            "weaknesses": weaknesses,
            "strengths": strengths,
        }

    def daily_report(self):
        return self._periodic_report("day")

    def weekly_report(self):
        return self._periodic_report("week")

    def monthly_report(self):
        return self._periodic_report("month")

    def session_statistics(self):
        grouped = defaultdict(list)
        for trade in self._closed_trades():
            grouped[trade.get("session", "UNKNOWN")].append(trade)
        return self._group_metrics(grouped)

    def killzone_statistics(self):
        grouped = defaultdict(list)
        for trade in self._closed_trades():
            grouped[trade.get("killzone", "UNKNOWN")].append(trade)
        return self._group_metrics(grouped)

    def coin_statistics(self):
        grouped = defaultdict(list)
        for trade in self._closed_trades():
            grouped[trade.get("symbol", "UNKNOWN")].append(trade)
        return self._group_metrics(grouped)

    def timeframe_statistics(self):
        grouped = defaultdict(list)
        for snapshot in self._snapshots:
            grouped[snapshot.get("timeframe", "UNKNOWN")].append(snapshot)
        return {
            timeframe: self._snapshot_group_metrics(items)
            for timeframe, items in grouped.items()
        }

    def market_phase_statistics(self):
        grouped = defaultdict(list)
        for trade in self._closed_trades():
            grouped[trade.get("market_phase", "UNKNOWN")].append(trade)
        return self._group_metrics(grouped)

    def setup_statistics(self):
        grouped = defaultdict(list)
        for trade in self._closed_trades():
            setup = trade.get("analysis", {}).get("decision", {}).get("action") or trade.get("side", "UNKNOWN")
            grouped[setup].append(trade)
        return self._group_metrics(grouped)

    def engine_statistics(self):
        return {engine: stats.copy() for engine, stats in self._engine_stats.items()}

    def confidence_quality(self):
        return self._bucket_quality("confidence")

    def confluence_quality(self):
        return self._bucket_quality("confluence_score")

    def risk_quality(self):
        closed = self._closed_trades()
        if not closed:
            return {"average_rr": 0, "average_risk_reward": 0, "risk_adjusted_winrate": 0}

        risk_values = [trade.get("rr") or trade.get("pnl_rr") or 0 for trade in closed]
        avg_rr = sum(risk_values) / len(risk_values)
        risk_adjusted_winrate = sum(1 for trade in closed if trade.get("result") == "WIN") / len(closed) * 100
        return {
            "average_rr": round(avg_rr, 2),
            "average_risk_reward": round(avg_rr, 2),
            "risk_adjusted_winrate": round(risk_adjusted_winrate, 2),
        }

    def tp_sl_analysis(self):
        closed = self._closed_trades()
        if not closed:
            return {"tp1_hit_rate": 0, "tp2_hit_rate": 0, "tp3_hit_rate": 0, "stop_rate": 0}

        total = len(closed)
        return {
            "tp1_hit_rate": round(sum(1 for trade in closed if trade.get("tp1_hit") or trade.get("result") == "WIN") / total * 100, 2),
            "tp2_hit_rate": round(sum(1 for trade in closed if trade.get("tp2_hit") or trade.get("pnl_rr", 0) >= 2) / total * 100, 2),
            "tp3_hit_rate": round(sum(1 for trade in closed if trade.get("tp3_hit") or trade.get("pnl_rr", 0) >= 3) / total * 100, 2),
            "stop_rate": round(sum(1 for trade in closed if trade.get("result") == "LOSS") / total * 100, 2),
        }

    def performance_trend(self):
        closed = self._closed_trades()
        if len(closed) < 3:
            return {"direction": "FLAT", "slope": 0, "series": []}

        rolling = []
        for index in range(0, len(closed)):
            window = closed[max(0, index - 4): index + 1]
            rolling.append(sum(self._trade_value(trade) for trade in window) / len(window))

        slope = rolling[-1] - rolling[0]
        direction = "UP" if slope > 0 else "DOWN" if slope < 0 else "FLAT"
        return {"direction": direction, "slope": round(slope, 4), "series": [round(value, 4) for value in rolling]}

    def weakness_report(self):
        closed = self._closed_trades()
        if not closed:
            return []

        weaknesses = []
        if self.confidence_quality().get("calibration_gap", 0) > 15:
            weaknesses.append("Confidence calibration is loose")
        if self.confluence_quality().get("calibration_gap", 0) > 15:
            weaknesses.append("Confluence does not predict outcome well enough")
        if self.tp_sl_analysis().get("stop_rate", 0) > 55:
            weaknesses.append("Stop loss rate is elevated")
        if self.performance_trend().get("direction") == "DOWN":
            weaknesses.append("Recent performance is deteriorating")
        return weaknesses

    def strength_report(self):
        closed = self._closed_trades()
        if not closed:
            return []

        strengths = []
        metrics = self._metrics(closed)
        if metrics.get("winrate", 0) >= 55:
            strengths.append("Win rate is competitive")
        if metrics.get("profit_factor", 0) >= 1.3:
            strengths.append("Profit factor is healthy")
        if self._best_setup_name():
            strengths.append(f"Best setup: {self._best_setup_name()}")
        if self.performance_trend().get("direction") == "UP":
            strengths.append("Recent performance is improving")
        return strengths

    def recommendations_for_decision_engine(self):
        summary = self.summary()
        return {
            "preferred_setups": self._top_keys(self.setup_statistics()),
            "preferred_sessions": self._top_keys(self.session_statistics()),
            "preferred_killzones": self._top_keys(self.killzone_statistics()),
            "preferred_phases": self._top_keys(self.market_phase_statistics()),
            "confidence_floor": self._confidence_floor(),
            "confluence_floor": self._confluence_floor(),
            "risk_floor": 1.0 if summary["profit_factor"] >= 1.0 else 1.2,
            "weight_adjustments": self._weight_adjustments(),
            "notes": self.strength_report() + self.weakness_report(),
        }

    def report_bundle(self):
        """Decision Engine'in kullanabileceği yapılandırılmış çıktı üretir."""
        return {
            "analysis": self.analysis_summary(),
            "summary": self.summary(),
            "daily": self.daily_report(),
            "weekly": self.weekly_report(),
            "monthly": self.monthly_report(),
            "recommendations": self.recommendations_for_decision_engine(),
            "engine_statistics": self.engine_statistics(),
            "confidence_quality": self.confidence_quality(),
            "confluence_quality": self.confluence_quality(),
            "risk_quality": self.risk_quality(),
            "tp_sl_analysis": self.tp_sl_analysis(),
            "performance_trend": self.performance_trend(),
            "strengths": self.strength_report(),
            "weaknesses": self.weakness_report(),
        }

    def analysis_summary(self):
        """Kaydedilen analiz snapshot'larının agregasyonunu döndürür."""
        if not self._snapshots:
            return {
                "total_snapshots": 0,
                "symbols": {},
                "timeframes": {},
                "latest_snapshot": None,
            }

        symbols = defaultdict(int)
        timeframes = defaultdict(int)
        for snapshot in self._snapshots:
            symbols[snapshot.get("symbol", "UNKNOWN")] += 1
            timeframes[snapshot.get("timeframe", "UNKNOWN")] += 1

        return {
            "total_snapshots": len(self._snapshots),
            "symbols": dict(symbols),
            "timeframes": dict(timeframes),
            "latest_snapshot": copy.deepcopy(self._snapshots[-1]),
        }

    def _ensure_store(self):
        if self.db_path:
            path = Path(self.db_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.db_path) as connection:
                self._create_tables(connection)

    def _create_tables(self, connection):
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS analysis_snapshots (
                id TEXT PRIMARY KEY,
                timestamp INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                status TEXT NOT NULL,
                opened_at INTEGER NOT NULL,
                closed_at INTEGER,
                payload TEXT NOT NULL
            )
            """
        )
        connection.commit()

    def _persist_snapshot(self, snapshot):
        if not self.db_path:
            return
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO analysis_snapshots (id, timestamp, symbol, timeframe, payload) VALUES (?, ?, ?, ?, ?)",
                (snapshot["id"], snapshot["timestamp"], snapshot["symbol"], snapshot["timeframe"], json.dumps(snapshot, default=str)),
            )
            connection.commit()

    def _persist_trade(self, trade):
        if not self.db_path:
            return
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO trades (id, symbol, side, status, opened_at, closed_at, payload) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (trade["id"], trade["symbol"], trade["side"], trade["status"], trade["opened_at"], trade.get("closed_at"), json.dumps(trade, default=str)),
            )
            connection.commit()

    def _latest_snapshot(self, symbol=None):
        if not self._snapshots:
            return None
        if symbol is None:
            return self._snapshots[-1]
        for snapshot in reversed(self._snapshots):
            if snapshot.get("symbol") == symbol:
                return snapshot
        return self._snapshots[-1]

    def _find_trade(self, trade_id):
        for trade in self._trades:
            if trade["id"] == trade_id:
                return trade
        return None

    def _infer_result(self, trade, exit_price):
        side = trade.get("side", "NONE")
        entry = trade.get("entry")
        stop_loss = trade.get("stop_loss")
        if entry is None or stop_loss is None:
            return "WIN"
        if side == "LONG":
            return "WIN" if exit_price >= entry else "LOSS"
        if side == "SHORT":
            return "WIN" if exit_price <= entry else "LOSS"
        return "WIN" if exit_price >= entry else "LOSS"

    def _calculate_trade_rr(self, trade, exit_price, result):
        entry = trade.get("entry")
        stop_loss = trade.get("stop_loss")
        if entry is None or stop_loss is None:
            return 0.0

        risk = abs(entry - stop_loss)
        if risk <= 0:
            return 0.0

        side = trade.get("side", "NONE")
        if side == "SHORT":
            rr = (entry - exit_price) / risk
        else:
            rr = (exit_price - entry) / risk

        if result == "LOSS":
            rr = -abs(rr)
        return round(rr, 4)

    def _update_engine_stats(self, trade):
        analysis = trade.get("analysis") or {}
        breakdown = {
            "signal": analysis.get("signal", {}),
            "confluence": analysis.get("confluence", {}),
            "risk": analysis.get("risk", {}),
            "decision": analysis.get("decision", {}),
        }

        for engine_name in breakdown:
            stats = self._engine_stats[engine_name]
            stats["total"] += 1
            if trade.get("result") == "WIN":
                stats["wins"] += 1
            elif trade.get("result") == "LOSS":
                stats["losses"] += 1

    def _closed_trades(self):
        return [trade for trade in self._trades if trade.get("status") == "CLOSED"]

    def _metrics(self, trades):
        wins = [trade for trade in trades if trade.get("result") == "WIN"]
        losses = [trade for trade in trades if trade.get("result") == "LOSS"]
        r_values = [trade.get("pnl_rr") or 0 for trade in trades]

        profit = sum(value for value in r_values if value > 0)
        loss = abs(sum(value for value in r_values if value < 0))
        profit_factor = profit / loss if loss > 0 else profit
        expectancy = sum(r_values) / len(r_values)
        average_r = expectancy
        winrate = (len(wins) / len(trades)) * 100
        max_drawdown = self._max_drawdown(r_values)
        sharpe_like = self._sharpe_like(r_values)
        average_hold_seconds = statistics.mean(trade.get("hold_seconds", 0) for trade in trades)
        best_streak, worst_streak = self._streaks(trades)

        return {
            "winrate": round(winrate, 2),
            "expectancy": round(expectancy, 4),
            "profit_factor": round(profit_factor, 4),
            "average_r": round(average_r, 4),
            "max_drawdown": round(max_drawdown, 4),
            "sharpe_like": round(sharpe_like, 4),
            "average_hold_seconds": round(average_hold_seconds, 2),
            "best_streak": best_streak,
            "worst_streak": worst_streak,
        }

    def _group_metrics(self, grouped):
        output = {}
        for key, trades in grouped.items():
            if not trades:
                continue
            metrics = self._metrics(trades)
            output[key] = {
                "total": len(trades),
                "wins": len([trade for trade in trades if trade.get("result") == "WIN"]),
                "losses": len([trade for trade in trades if trade.get("result") == "LOSS"]),
                **metrics,
            }
        return output

    def _snapshot_group_metrics(self, snapshots):
        if not snapshots:
            return {"total": 0, "avg_confidence": 0, "avg_confluence": 0, "avg_risk_rr": 0}
        return {
            "total": len(snapshots),
            "avg_confidence": round(statistics.mean(self._snapshot_value(snapshot, "signal", "confidence") or 0 for snapshot in snapshots), 2),
            "avg_confluence": round(statistics.mean(self._snapshot_value(snapshot, "confluence", "score") or 0 for snapshot in snapshots), 2),
            "avg_risk_rr": round(statistics.mean((snapshot.get("risk") or {}).get("rr") or 0 for snapshot in snapshots), 2),
        }

    def _bucket_quality(self, field_name):
        closed = self._closed_trades()
        if not closed:
            return {"calibration_gap": 0, "buckets": []}

        buckets = []
        for lower in range(0, 101, 20):
            upper = lower + 19
            items = [trade for trade in closed if lower <= (trade.get(field_name, 0) or 0) <= upper]
            if not items:
                continue
            winrate = len([trade for trade in items if trade.get("result") == "WIN"]) / len(items) * 100
            avg_conf = statistics.mean(trade.get(field_name, 0) or 0 for trade in items)
            buckets.append({"range": f"{lower}-{upper}", "total": len(items), "winrate": round(winrate, 2), "avg": round(avg_conf, 2)})

        if not buckets:
            return {"calibration_gap": 0, "buckets": []}

        calibration_gap = statistics.mean(abs(bucket["winrate"] - bucket["avg"]) for bucket in buckets)
        return {"calibration_gap": round(calibration_gap, 2), "buckets": buckets}

    def _streaks(self, trades):
        best = 0
        worst = 0
        current = 0
        current_sign = None

        for trade in trades:
            sign = 1 if trade.get("result") == "WIN" else -1
            if current_sign == sign or current_sign is None:
                current += sign
                current_sign = sign
            else:
                best = max(best, current)
                worst = min(worst, current)
                current = sign
                current_sign = sign

        best = max(best, current)
        worst = min(worst, current)
        return best, worst

    def _max_drawdown(self, r_values):
        peak = 0.0
        equity = 0.0
        drawdown = 0.0
        for value in r_values:
            equity += value
            peak = max(peak, equity)
            drawdown = min(drawdown, equity - peak)
        return abs(drawdown)

    def _sharpe_like(self, r_values):
        if len(r_values) < 2:
            return 0.0
        mean = statistics.mean(r_values)
        stdev = statistics.pstdev(r_values)
        if stdev == 0:
            return 0.0
        return mean / stdev

    def _periodic_report(self, period):
        closed = self._closed_trades()
        if not closed:
            return {"period": period, "total": 0}

        return {
            "period": period,
            "total": len(closed),
            "summary": self.summary(),
            "recommendations": self.recommendations_for_decision_engine(),
        }

    def _top_keys(self, mapping):
        if not mapping:
            return []
        ordered = sorted(mapping.items(), key=lambda item: (item[1].get("winrate", 0), item[1].get("profit_factor", 0)), reverse=True)
        return [key for key, _ in ordered[:3]]

    def _confidence_floor(self):
        quality = self.confidence_quality()
        if not quality.get("buckets"):
            return 0
        return round(min(bucket["avg"] for bucket in quality["buckets"]), 2)

    def _confluence_floor(self):
        quality = self.confluence_quality()
        if not quality.get("buckets"):
            return 0
        return round(min(bucket["avg"] for bucket in quality["buckets"]), 2)

    def _weight_adjustments(self):
        summary = self.summary()
        confidence_floor = self._confidence_floor()
        confluence_floor = self._confluence_floor()
        return {
            "confidence": 0.1 if confidence_floor >= 75 else -0.05,
            "confluence": 0.1 if confluence_floor >= 70 else -0.05,
            "risk": -0.1 if summary.get("max_drawdown", 0) > 5 else 0.05,
        }

    def _best_setup_name(self):
        setups = self.setup_statistics()
        if not setups:
            return None
        return self._top_keys(setups)[0] if self._top_keys(setups) else None

    def _empty_summary(self):
        return {
            "total_trades": 0,
            "open_trades": 0,
            "wins": 0,
            "losses": 0,
            "winrate": 0,
            "expectancy": 0,
            "profit_factor": 0,
            "average_r": 0,
            "max_drawdown": 0,
            "sharpe_like": 0,
            "average_hold_seconds": 0,
            "best_streak": 0,
            "worst_streak": 0,
            "session_statistics": {},
            "killzone_statistics": {},
            "coin_statistics": {},
            "timeframe_statistics": {},
            "market_phase_statistics": {},
            "setup_statistics": {},
            "engine_statistics": {},
            "confidence_quality": {"calibration_gap": 0, "buckets": []},
            "confluence_quality": {"calibration_gap": 0, "buckets": []},
            "risk_quality": {"average_rr": 0, "average_risk_reward": 0, "risk_adjusted_winrate": 0},
            "tp_sl_analysis": {"tp1_hit_rate": 0, "tp2_hit_rate": 0, "tp3_hit_rate": 0, "stop_rate": 0},
            "performance_trend": {"direction": "FLAT", "slope": 0, "series": []},
            "weaknesses": [],
            "strengths": [],
        }

    def _uuid(self, prefix):
        return f"{prefix}_{uuid.uuid4().hex}"

    def _snapshot_value(self, snapshot, *path):
        value = snapshot or {}
        for key in path:
            if not isinstance(value, dict):
                return None
            value = value.get(key)
        return value

    def _value_from(self, mapping, key, default=None):
        if isinstance(mapping.get(key), (int, float, str)):
            return mapping.get(key)
        return default

    def _compact_structure(self, analysis):
        structure = analysis.get("structure") or []
        compact = []
        for item in structure[-15:]:
            compact.append(
                {
                    "index": item.get("index"),
                    "label": item.get("label"),
                    "direction": item.get("direction"),
                    "bos": item.get("bos", False),
                    "choch": item.get("choch", False),
                }
            )
        return compact

    def _extract_session(self, analysis):
        session = analysis.get("session") or {}
        if isinstance(session, dict):
            return session.get("session") or session.get("name") or "UNKNOWN"
        return str(session) if session else "UNKNOWN"

    def _extract_killzone(self, analysis):
        killzone = analysis.get("killzone") or {}
        if isinstance(killzone, dict):
            return killzone.get("name") or killzone.get("session") or "UNKNOWN"
        return str(killzone) if killzone else "UNKNOWN"

    def _trade_value(self, trade):
        if trade.get("pnl_rr") is not None:
            return trade["pnl_rr"]
        if trade.get("rr") is not None:
            return trade["rr"] if trade.get("result") == "WIN" else -abs(trade["rr"])
        return 0.0
