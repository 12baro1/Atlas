"""
trade_journal.py
Atlas Trade Journal & Performance Analytics Engine
"""

from __future__ import annotations

import copy
import gzip
import json
import math
import sqlite3
import statistics
import time
import uuid
from collections import defaultdict
from pathlib import Path


def _gzip_payload(payload):
    """Snapshot'ı gzip'li BLOB'a çevirir (arşivde yer kazandırır)."""
    return gzip.compress(json.dumps(payload, default=str).encode("utf-8"))


class TradeJournal:
    """Atlas analiz, trade ve performans kayıtlarını tek bir yerde toplar."""

    def __init__(self, db_path=None):
        self.db_path = str(db_path) if db_path else None
        self._snapshots = []
        self._trades = []
        self._signal_outcomes = []
        self._manual_trades = []
        self._engine_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "total": 0})
        self._ensure_store()
        self._enforce_retention()

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
        self._enforce_retention()
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

    def open_trades(self, symbol=None):
        """Açık (OPEN) trade listesini döner; isteğe bağlı sembol filtreli."""
        out = []
        for trade in self._trades:
            if trade.get("status") != "OPEN":
                continue
            if symbol and trade.get("symbol") != symbol:
                continue
            out.append(trade)
        return out

    def closed_trades(self, symbol=None):
        """Kapanmış (CLOSED) trade listesini döner; isteğe bağlı sembol filtreli."""
        out = []
        for trade in self._trades:
            if trade.get("status") != "CLOSED":
                continue
            if symbol and trade.get("symbol") != symbol:
                continue
            out.append(trade)
        return out

    def resolve_open_signal(self, trade, candles):
        """Açık bir trade'i verilen mumlar üzerinden SL/TP vuruşuyla kapatır.

        Mum zamanları trade açılışından sonraki (>) kapanış mumu baz alınır ve
        ilk vuruş (SL ya da TP) sonucu belirler. Kapanmamışsa None döner.
        """
        opened_at = trade.get("opened_at") or 0
        side = trade.get("side", "LONG")
        entry = trade.get("entry")
        stop_loss = trade.get("stop_loss")
        tps = [trade.get(k) for k in ("tp1", "tp2", "tp3")]
        tps = [tp for tp in tps if isinstance(tp, (int, float)) and tp]

        for candle in candles:
            ts = getattr(candle, "time", None)
            if ts is None or ts <= opened_at:
                continue

            high = getattr(candle, "high", None)
            low = getattr(candle, "low", None)
            if high is None or low is None:
                continue

            hit_tp = False
            if tps:
                tp = tps[0]
                if side == "LONG":
                    hit_sl = low <= stop_loss if stop_loss is not None else False
                    hit_tp = high >= tp
                else:
                    hit_sl = high >= stop_loss if stop_loss is not None else False
                    hit_tp = low <= tp
            else:
                if side == "LONG":
                    hit_sl = low <= stop_loss if stop_loss is not None else False
                else:
                    hit_sl = high >= stop_loss if stop_loss is not None else False

            # SL'ye TP'den önce vurulursa LOSS, önce TP vurulursa WIN
            if hit_sl and hit_tp:
                # Intrabar sıralaması bilinmediği için muhafazakâr: SL'yi önce kabul et.
                hit_tp = False
            if hit_sl:
                exit_price = stop_loss
                return self.close_trade(
                    trade["id"], exit_price, result="LOSS",
                    timestamp=ts, reason="stop_loss_hit",
                )
            if hit_tp:
                exit_price = tps[0]
                return self.close_trade(
                    trade["id"], exit_price, result="WIN",
                    timestamp=ts, reason="target_hit",
                )
        return None

    def resolve_open_signals(self, candles_by_symbol):
        """Geçerli mum verisiyle tüm açık sinyalleri çözer; kapananları döner."""
        closed = []
        for symbol, candles in candles_by_symbol.items():
            for trade in self.open_trades(symbol=symbol):
                closed_trade = self.resolve_open_signal(trade, candles)
                if closed_trade is not None:
                    closed.append(closed_trade)
        return closed

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

    def _connect(self):
        """Kilitli veritabanına erişim için busy_timeout ile bağlantı açar."""
        connection = sqlite3.connect(self.db_path, timeout=30.0)
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _ensure_store(self):
        if self.db_path:
            path = Path(self.db_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                self._create_tables(connection)
            self._load_from_db()

    def _retention_settings(self):
        try:
            from config import Config
        except Exception:
            Config = None
        retention_days = int(getattr(Config, "JOURNAL_RETENTION_DAYS", 30) if Config else 30)
        max_snapshots = int(getattr(Config, "JOURNAL_RETENTION_MAX_SNAPSHOTS", 30000) if Config else 30000)
        return retention_days, max_snapshots

    def _enforce_retention(self):
        """Büyüme kontrolü: eski snapshot'lar kalıcı analiz tablosundan arşive taşınır.

        - Eşik: JOURNAL_RETENTION_DAYS (gün) ve JOURNAL_RETENTION_MAX_SNAPSHOTS.
        - Arşivleme geri alınamaz silme DEĞİL: satırlar analysis_snapshots_archive
          tablosuna (gzip'lenmiş payload ile) taşınır ve bellekteki _snapshots /
          ana tablodan ayıklanır. Böylece atlas_journal.db büyümesi sınırlanır,
          geçmiş veri kaybolmaz.
        """
        if not self.db_path or not Path(self.db_path).exists():
            return
        retention_days, max_snapshots = self._retention_settings()
        if retention_days <= 0 and max_snapshots <= 0:
            return

        cutoff_ms = int(time.time() * 1000) - int(retention_days) * 86400 * 1000 if retention_days > 0 else 0
        self._snapshots.sort(key=lambda s: s.get("timestamp", 0))
        stale = [
            s for s in self._snapshots
            if (retention_days > 0 and s.get("timestamp", 0) < cutoff_ms)
            or (max_snapshots > 0 and len(self._snapshots) - self._snapshots.index(s) - 1 >= max_snapshots)
        ]

        if not stale:
            return
        stale_ids = {s.get("id") for s in stale}
        archived = 0
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_snapshots_archive (
                    id TEXT PRIMARY KEY,
                    timestamp INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    payload BLOB NOT NULL
                )
                """
            )
            for s in stale:
                try:
                    connection.execute(
                        "INSERT OR REPLACE INTO analysis_snapshots_archive (id, timestamp, symbol, timeframe, payload) VALUES (?, ?, ?, ?, ?)",
                        (
                            s.get("id"),
                            s.get("timestamp", 0),
                            s.get("symbol", "UNKNOWN"),
                            s.get("timeframe", "multi"),
                            _gzip_payload(s),
                        ),
                    )
                    connection.execute("DELETE FROM analysis_snapshots WHERE id = ?", (s.get("id"),))
                    archived += 1
                except Exception:
                    continue
            connection.commit()
        self._snapshots = [s for s in self._snapshots if s.get("id") not in stale_ids]
        if archived:
            self._vacuum_if_large()

    def _vacuum_if_large(self):
        """Arşiv sonrası DB fiziksel olarak küçülür mü? (freepages isteğe bağlı)"""
        try:
            with self._connect() as connection:
                connection.execute("PRAGMA auto_vacuum=INCREMENTAL")
                connection.execute("PRAGMA incremental_vacuum")
                connection.execute("PRAGMA optimize")
                connection.commit()
        except Exception:
            pass

    def archive_stats(self):
        """Arşiv hakkında bilgi döner: gerçek silinmemiş, tabloya taşınmış satırlar."""
        if not self.db_path or not Path(self.db_path).exists():
            return {"archived_snapshots": 0, "active_snapshots": len(self._snapshots)}
        try:
            with self._connect() as connection:
                count = connection.execute("SELECT COUNT(*) FROM analysis_snapshots_archive").fetchone()[0]
            return {"archived_snapshots": count, "active_snapshots": len(self._snapshots)}
        except Exception:
            return {"archived_snapshots": 0, "active_snapshots": len(self._snapshots)}

    def _load_from_db(self):
        """Kalıcı SQLite'dan snapshot ve trade kayıtlarını belleğe geri yükler."""
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            with self._connect() as connection:
                rows = connection.execute("SELECT id, timestamp, symbol, timeframe, payload FROM analysis_snapshots ORDER BY timestamp").fetchall()
                for _id, _ts, _sym, _tf, payload in rows:
                    try:
                        self._snapshots.append(json.loads(payload))
                    except Exception:
                        continue
                trades = connection.execute("SELECT id, symbol, side, status, opened_at, closed_at, payload FROM trades ORDER BY opened_at").fetchall()
                for _id, _symbol, _side, _status, _opened_at, _closed_at, payload in trades:
                    try:
                        self._trades.append(json.loads(payload))
                    except Exception:
                        continue
                outcomes = connection.execute("SELECT signal_id, symbol, direction, timeframe, status, opened_at, resolved_at, payload FROM signal_outcomes ORDER BY opened_at").fetchall()
                for _sid, _sym, _dir, _tf, _status, _opened_at, _resolved_at, payload in outcomes:
                    try:
                        self._signal_outcomes.append(json.loads(payload))
                    except Exception:
                        continue
                manual = connection.execute("SELECT id, signal_id, symbol, side, status, opened_at, closed_at, payload FROM manual_trades ORDER BY opened_at").fetchall()
                for _id, _sid, _sym, _side, _status, _opened_at, _closed_at, payload in manual:
                    try:
                        self._manual_trades.append(json.loads(payload))
                    except Exception:
                        continue
        except Exception:
            return

    def _create_tables(self, connection):
        # Yeni DB'lerde auto_vacuum=INCREMENTAL: arşivleme sonrası DELETEdilen
        # sayfalar `PRAGMA incremental_vacuum` ile fiziksel olarak geri kazanılır.
        # (auto_vacuum=0 ise incremental_vacuum no-op kalır ve dosya küçülmez.)
        try:
            connection.execute("PRAGMA auto_vacuum=INCREMENTAL")
        except Exception:
            pass
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
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS signal_outcomes (
                signal_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                status TEXT NOT NULL,
                opened_at INTEGER NOT NULL,
                resolved_at INTEGER,
                payload TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS manual_trades (
                id TEXT PRIMARY KEY,
                signal_id TEXT,
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
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO analysis_snapshots (id, timestamp, symbol, timeframe, payload) VALUES (?, ?, ?, ?, ?)",
                (snapshot["id"], snapshot["timestamp"], snapshot["symbol"], snapshot["timeframe"], json.dumps(snapshot, default=str)),
            )
            connection.commit()

    def _persist_trade(self, trade):
        if not self.db_path:
            return
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO trades (id, symbol, side, status, opened_at, closed_at, payload) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (trade["id"], trade["symbol"], trade["side"], trade["status"], trade["opened_at"], trade.get("closed_at"), json.dumps(trade, default=str)),
            )
            connection.commit()

    def _persist_signal_outcome(self, outcome):
        if not self.db_path:
            return
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO signal_outcomes (signal_id, symbol, direction, timeframe, status, opened_at, resolved_at, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    outcome.get("signal_id"),
                    outcome.get("symbol"),
                    outcome.get("direction"),
                    outcome.get("timeframe"),
                    outcome.get("status"),
                    outcome.get("opened_at"),
                    outcome.get("resolved_at"),
                    json.dumps(outcome, default=str),
                ),
            )
            connection.commit()

    def _persist_manual_trade(self, manual_trade):
        if not self.db_path:
            return
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO manual_trades (id, signal_id, symbol, side, status, opened_at, closed_at, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    manual_trade.get("id"),
                    manual_trade.get("signal_id"),
                    manual_trade.get("symbol"),
                    manual_trade.get("side"),
                    manual_trade.get("status"),
                    manual_trade.get("opened_at"),
                    manual_trade.get("closed_at"),
                    json.dumps(manual_trade, default=str),
                ),
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
        # Başka bir sembolün snapshot'unu bu trade'e iliştirme; yanlış
        # session/killzone/killzone/market_phase atıflarını önle.
        return None

    def _find_trade(self, trade_id):
        for trade in self._trades:
            if trade["id"] == trade_id:
                return trade
        return None

    def _infer_result(self, trade, exit_price):
        side = trade.get("side", "NONE")
        entry = trade.get("entry")
        stop_loss = trade.get("stop_loss")
        if entry is None or stop_loss is None or exit_price is None:
            # Yetersiz/geçersiz veriden kazanç uydurma; ölçümlere dahil etme.
            return "UNKNOWN"
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

    def resolve_signal_outcome(self, outcome, candles, max_steps=None):
        """Teorik sinyal sonucunu mumlar üzerinde ilerletir.

        Partial TP mantığı desteklenir: birden fazla TP varsa her TP eşit
        ağırlıkta kısmi kapanış oluşturur (ör. 3 TP → %33.3). TP1'den sonra
        koruyucu stop breakeven'e, TP2'den sonra TP1 seviyesine taşınır.
        TP sonrası SL gelen senaryo 'WIN' olarak değil gerçekleşen kısmi R
        ile işaretlenir.

        Dönüş: güncellenmiş outcome (kapanmışsa) veya None (henüz açık).
        """
        if outcome.get("status") != "PENDING":
            return outcome

        symbol = outcome.get("symbol")
        entry = self._num(outcome.get("entry"))
        stop_loss = self._num(outcome.get("stop_loss"))
        if entry is None or stop_loss is None:
            return None

        candles = self._candles_for_symbol(candles, symbol)
        matching = [c for c in candles if getattr(c, "time", 0) > outcome.get("opened_at", 0)]
        matching = matching[: max_steps] if max_steps else matching
        if not matching:
            return None

        side = outcome.get("direction", "LONG")
        tps = [(i + 1, self._num(outcome.get(f"tp{i + 1}"))) for i in range(3)]
        tps = [(i, tp) for i, tp in tps if tp is not None]
        weights = self._norm_partial_weights(outcome)

        risk = abs(entry - stop_loss)
        if risk <= 0:
            return None

        reached = list(outcome.get("tps_hit") or [])
        trailing_stop = self._num(outcome.get("trailing_stop")) or stop_loss
        realized = 0.0
        hit_sl = bool(outcome.get("hit_sl"))
        mfe = float(outcome.get("max_favorable_excursion") or 0.0)
        mae = float(outcome.get("max_adverse_excursion") or 0.0)
        closed_all = len(reached) >= len(tps) and len(tps) > 0

        for candle in matching:
            low = self._num(getattr(candle, "low", None))
            high = self._num(getattr(candle, "high", None))
            close = self._num(getattr(candle, "close", None))
            if low is None or high is None:
                continue

            # MFE / MAE takibi
            if side == "LONG":
                if high is not None:
                    mfe = max(mfe, (high - entry))
                if low is not None:
                    mae = min(mae, (entry - low))
            else:
                if high is not None:
                    mae = min(mae, (entry - high))
                if low is not None:
                    mfe = max(mfe, (entry - low))

            if closed_all:
                break

            # SL önceliği: kalan pozisyon önce stop'tan çıkar.
            sl_zone_hit = False
            current_stop = trailing_stop
            if side == "LONG":
                if current_stop is not None and low <= current_stop:
                    sl_zone_hit = True
            elif current_stop is not None and high >= current_stop:
                sl_zone_hit = True

            if sl_zone_hit and not hit_sl:
                hit_sl = True
                closed_frac_of_current = sum(self._weight_for(weights, i) for i in reached)
                remaining = max(0.0, 1.0 - closed_frac_of_current)
                if side == "LONG":
                    rr_stop = (current_stop - entry) / risk
                else:
                    rr_stop = (entry - current_stop) / risk
                realized += remaining * rr_stop
                closed_all = True
                break

            # TP'leri sırayla dene
            for level_no, tp_price in tps:
                if level_no in reached:
                    continue
                valid_zone = (high >= tp_price) if side == "LONG" else (low <= tp_price)
                if not valid_zone:
                    continue
                weight = self._weight_for(weights, level_no)
                if side == "LONG":
                    rr_tp = (tp_price - entry) / risk
                else:
                    rr_tp = (entry - tp_price) / risk
                realized += weight * rr_tp
                reached.append(level_no)
                # Koruma stopunu taşı
                if len(reached) == 1 and 1 in reached:
                    if side == "LONG":
                        trailing_stop = max(current_stop if current_stop is not None else stop_loss, entry)
                    else:
                        trailing_stop = min(current_stop if current_stop is not None else stop_loss, entry)
                elif 2 in reached and 3 not in reached:
                    tp1 = self._num(outcome.get("tp1"))
                    if tp1 is not None:
                        trailing_stop = tp1
                else:
                    trailing_stop = current_stop
                if len(reached) >= len(tps):
                    closed_all = True
                    break

        # Güncelle
        for level_no, _tp in tps:
            outcome[f"hit_tp{level_no}"] = level_no in reached
        outcome["hit_sl"] = hit_sl
        outcome["tps_hit"] = reached
        outcome["trailing_stop"] = trailing_stop
        outcome["realized_r"] = round(realized, 4)
        outcome["max_favorable_excursion"] = round(mfe, 8)
        outcome["max_adverse_excursion"] = round(mae, 8)

        if closed_all or hit_sl:
            return self._finalize_signal_outcome(outcome)

        # Expiry kontrolü
        opened_at = int(outcome.get("opened_at") or 0)
        expiry_hours = self._signal_outcome_expiry_hours()
        last_ts = getattr(matching[-1], "time", 0) or int(time.time() * 1000)
        if expiry_hours > 0 and last_ts > opened_at + int(expiry_hours * 3600 * 1000):
            outcome["status"] = "EXPIRED"
            outcome["resolved_at"] = last_ts
            outcome["final_result"] = "EXPIRED"
            self._persist_signal_outcome(outcome)
            return outcome

        self._persist_signal_outcome(outcome)
        return None

    def _finalize_signal_outcome(self, outcome):
        """TP/sl ile kapanmış sinyali kalıcı duruma geçirir."""
        realized = float(outcome.get("realized_r") or 0.0)
        if outcome.get("hit_sl") and not outcome.get("tps_hit"):
            outcome["status"] = "SL"
            outcome["final_result"] = "LOSS"
        elif outcome.get("hit_sl") and outcome.get("tps_hit"):
            # TP sonrası SL: '%WIN' değil, gerçekleşen kısmi R işaretlenir.
            outcome["status"] = "SL"
            outcome["final_result"] = "PARTIAL"
        elif len(outcome.get("tps_hit") or []) >= 3:
            outcome["status"] = "TP3"
            outcome["final_result"] = "WIN"
        elif len(outcome.get("tps_hit") or []) == 2:
            outcome["status"] = "TP2"
            outcome["final_result"] = "WIN"
        elif len(outcome.get("tps_hit") or []) == 1:
            outcome["status"] = "TP1"
            outcome["final_result"] = "WIN"
        else:
            outcome["status"] = "PENDING"
            outcome["final_result"] = None
            self._persist_signal_outcome(outcome)
            return outcome
        outcome["resolved_at"] = int(time.time() * 1000)
        self._persist_signal_outcome(outcome)
        return outcome

    def expire_stale_signal_outcomes(self, now_ms=None, candles=None):
        """Expiry süresi geçm PENDING sinyalleri EXPIRED yapar."""
        now_ms = int(now_ms or time.time() * 1000)
        expiry_hours = self._signal_outcome_expiry_hours()
        expired = []
        for outcome in self._signal_outcomes:
            if outcome.get("status") != "PENDING":
                continue
            opened_at = int(outcome.get("opened_at") or 0)
            age = now_ms - opened_at
            if expiry_hours > 0 and age > expiry_hours * 3600 * 1000:
                outcome["status"] = "EXPIRED"
                outcome["resolved_at"] = now_ms
                outcome["final_result"] = "EXPIRED"
                self._persist_signal_outcome(outcome)
                expired.append(outcome)
        return expired

    def resolve_signal_outcomes(self, candles_by_symbol):
        """Tüm açık sinyal sonuçlarını ilerletir; kapananları döner."""
        resolved = []
        opened = list(self.open_signal_outcomes())
        for outcome in opened:
            symbol = outcome.get("symbol")
            candles = (candles_by_symbol or {}).get(symbol) or []
            updated = self.resolve_signal_outcome(outcome, candles)
            if updated is not None and updated.get("status") != "PENDING":
                resolved.append(updated)
        return resolved

    # ------------------------------------------------------------------
    # Manuel işlemler (MANUAL TRADE)
    # ------------------------------------------------------------------

    def open_manual_trade(self, *, signal_id, actual_entry=None, actual_stop=None, actual_tp=None,
                          position_size=None, opened_at=None, exit=None):
        """Kullanıcının gerçek işlemini bir sinyale bağlar.

        Sinyal bulunamazsa ya da aynı signal_id'ye ait açık manual trade
        varsa hata döner (duplicate koruması).
        """
        outcome = self.find_signal_outcome(signal_id) if signal_id else None
        if outcome is None:
            return None, "signal_not_found"
        for manual in self._manual_trades:
            if manual.get("signal_id") == signal_id:
                return manual, "already_open"

        now = int(opened_at or time.time() * 1000)
        manual = {
            "id": self._uuid("manual"),
            "signal_id": signal_id,
            "symbol": outcome.get("symbol"),
            "side": outcome.get("direction"),
            "status": "OPEN",
            "opened_at": now,
            "closed_at": None,
            "entry": self._norm_price(actual_entry) or self._num(outcome.get("entry")),
            "stop_loss": self._norm_price(actual_stop) or self._num(outcome.get("stop_loss")),
            "tp1": self._norm_price(actual_tp or outcome.get("tp1")),
            "tp2": self._norm_price(outcome.get("tp2")),
            "tp3": self._norm_price(outcome.get("tp3")),
            "position_size": position_size,
            "result": None,
            "pnl_rr": None,
            "pnl": None,
            "manual_exit_reason": None,
            "actual_exit": None,
            "setup_fingerprint": outcome.get("setup_fingerprint"),
            "regime": outcome.get("regime") or outcome.get("market_phase"),
            "grade": outcome.get("grade"),
            "confidence": outcome.get("confidence"),
            "timeframe": outcome.get("timeframe", "15m"),
        }
        self._manual_trades.append(manual)
        self._persist_manual_trade(manual)
        return manual, "opened"

    def close_manual_trade(self, manual_id=None, signal_id=None, *, actual_exit=None, result=None,
                           pnl=None, closed_at=None, manual_exit_reason=None):
        """Kullanıcının gerçek işlemini kapatır.

        result: WIN | LOSS | BREAKEVEN | MANUAL_CLOSE | CANCELLED.
        Result bilinmiyorsa actual_exit/entry/stop bazında otomatik infer edilir.
        """
        manual = None
        for candidate in self._manual_trades:
            if manual_id and candidate.get("id") == manual_id:
                manual = candidate
                break
            if signal_id and candidate.get("signal_id") == signal_id:
                manual = candidate
                break
        if manual is None:
            return None, "manual_not_found"
        if manual.get("status") == "CLOSED":
            return manual, "already_closed"

        closed_at = int(closed_at or time.time() * 1000)
        entry = self._num(manual.get("entry"))
        stop_loss = self._num(manual.get("stop_loss"))
        exit_price = self._num(actual_exit)
        if exit_price is None:
            exit_price = self._num(manual.get("actual_exit"))

        side = manual.get("side", "LONG")
        if result is None and exit_price is not None:
            if exit_price == entry:
                result = "BREAKEVEN"
            elif side == "LONG":
                result = "WIN" if exit_price > entry else "LOSS"
            else:
                result = "WIN" if exit_price < entry else "LOSS"
        result = (result or "MANUAL_CLOSE").upper()
        allowed = ("WIN", "LOSS", "BREAKEVEN", "MANUAL_CLOSE", "CANCELLED")
        if result not in allowed:
            result = "MANUAL_CLOSE"

        pnl_rr = 0.0
        if entry is not None and stop_loss is not None and exit_price is not None:
            risk = abs(entry - stop_loss)
            if risk > 0:
                if side == "LONG":
                    pnl_rr = (exit_price - entry) / risk
                else:
                    pnl_rr = (entry - exit_price) / risk
                if result == "LOSS":
                    pnl_rr = -abs(pnl_rr)
                elif result == "BREAKEVEN":
                    pnl_rr = 0.0
                pnl_rr = round(pnl_rr, 4)

        manual["status"] = "CLOSED"
        manual["closed_at"] = closed_at
        manual["actual_exit"] = exit_price
        manual["result"] = result
        manual["pnl_rr"] = pnl_rr
        manual["pnl"] = pnl
        manual["manual_exit_reason"] = manual_exit_reason
        self._persist_manual_trade(manual)
        return manual, "closed"

    def open_manual_trades(self, symbol=None):
        out = []
        for manual in self._manual_trades:
            if manual.get("status") != "OPEN":
                continue
            if symbol and manual.get("symbol") != symbol:
                continue
            out.append(manual)
        return out

    def closed_manual_trades(self, symbol=None):
        out = []
        for manual in self._manual_trades:
            if manual.get("status") != "CLOSED":
                continue
            if symbol and manual.get("symbol") != symbol:
                continue
            out.append(manual)
        return out

    # ------------------------------------------------------------------
    # Ayrı performans istatistikleri
    # ------------------------------------------------------------------

    def signal_performance(self):
        """SIGNAL PERFORMANCE: teorik sinyal sonuçları (tps / sl / expired)."""
        resolved = [o for o in self._signal_outcomes if o.get("status") != "PENDING"]
        if not resolved:
            return self._empty_signal_performance()
        terminal = [o for o in resolved if o.get("final_result") in ("WIN", "LOSS", "PARTIAL")]
        wins = [o for o in terminal if o.get("final_result") == "WIN"]
        losses = [o for o in terminal if o.get("final_result") == "LOSS"]
        partials = [o for o in terminal if o.get("final_result") == "PARTIAL"]
        r_values = [self._num(o.get("realized_r"), 0.0) for o in terminal]
        winrate = (len(wins) / len(terminal) * 100) if terminal else 0.0
        return {
            "total": len(resolved),
            "pending": len([o for o in resolved if o.get("status") == "PENDING"]),
            "closed": len(terminal),
            "wins": len(wins),
            "losses": len(losses),
            "partials": len(partials),
            "expired": len([o for o in resolved if o.get("status") == "EXPIRED"]),
            "cancelled": len([o for o in resolved if o.get("status") == "CANCELLED"]),
            "winrate": round(winrate, 2),
            "expectancy": round(sum(r_values) / len(r_values), 4) if r_values else 0.0,
            "profit_factor": self._profit_factor(r_values),
            "average_r": round(sum(r_values) / len(r_values), 4) if r_values else 0.0,
            "long": len([o for o in terminal if o.get("direction") == "LONG"]),
            "short": len([o for o in terminal if o.get("direction") == "SHORT"]),
            "tp1": len([o for o in terminal if o.get("hit_tp1")]),
            "tp2": len([o for o in terminal if o.get("hit_tp2")]),
            "tp3": len([o for o in terminal if o.get("hit_tp3")]),
            "sl": len([o for o in terminal if o.get("hit_sl")]),
        }

    def manual_trade_performance(self):
        """MANUAL TRADE PERFORMANCE (kullanıcının gerçek işlemleri)."""
        closed = self.closed_manual_trades()
        if not closed:
            return self._empty_manual_performance()
        wins = [m for m in closed if m.get("result") == "WIN"]
        losses = [m for m in closed if m.get("result") == "LOSS"]
        breakeven = [m for m in closed if m.get("result") == "BREAKEVEN"]
        r_values = [self._num(m.get("pnl_rr"), 0.0) for m in closed]
        return {
            "total": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "breakeven": len(breakeven),
            "cancelled": len([m for m in closed if m.get("result") == "CANCELLED"]),
            "open": len(self.open_manual_trades()),
            "winrate": round(len(wins) / len(closed) * 100, 2) if closed else 0.0,
            "expectancy": round(sum(r_values) / len(r_values), 4) if r_values else 0.0,
            "profit_factor": self._profit_factor(r_values),
            "average_r": round(sum(r_values) / len(r_values), 4) if r_values else 0.0,
        }

    # ------------------------------------------------------------------
    # Learning verisi (future-data guard: yalnızca kapanan + as-of)
    # ------------------------------------------------------------------

    def learning_records(self, *, as_of_ms=None, source="manual", symbol=None):
        """LearningEngine için geçmiş kayıtları döndürür.

        as_of_ms verilirse yalnızca bu andan ÖNCE kapanan kayıtlar gelir
        (future-data / look-ahead koruması). source="manual" manuel işlemleri,
        "signal" teorik sinyal sonuçlarını döndürür.
        """
        as_of_ms = int(as_of_ms) if as_of_ms else None
        if source == "manual":
            records = []
            for manual in self._manual_trades:
                if manual.get("status") != "CLOSED":
                    continue
                closed_at = int(manual.get("closed_at") or 0)
                if as_of_ms is not None and closed_at > as_of_ms:
                    continue
                if symbol and manual.get("symbol") != symbol:
                    continue
                records.append(self._manual_to_learning_record(manual))
            return records
        records = []
        for outcome in self._signal_outcomes:
            if outcome.get("status") == "PENDING":
                continue
            closed_at = int(outcome.get("resolved_at") or outcome.get("opened_at") or 0)
            if as_of_ms is not None and closed_at > as_of_ms:
                continue
            if symbol and outcome.get("symbol") != symbol:
                continue
            records.append(self._signal_to_learning_record(outcome))
        return records

    def _manual_to_learning_record(self, manual):
        wins = manual.get("result") in ("WIN",)
        r_value = self._num(manual.get("pnl_rr"), 0.0)
        return {
            "source": "manual",
            "direction": manual.get("side", "NONE"),
            "symbol": manual.get("symbol"),
            "closed_at": int(manual.get("closed_at") or manual.get("opened_at") or 0),
            "opened_at": int(manual.get("opened_at") or 0),
            "result": manual.get("result"),
            "win": wins,
            "r": r_value,
            "timeframe": self._manual_timeframe(manual),
            "setup_fingerprint": manual.get("setup_fingerprint"),
            "regime": manual.get("regime"),
            "grade": manual.get("grade"),
            "confidence": manual.get("confidence"),
        }

    def _signal_to_learning_record(self, outcome):
        win = outcome.get("final_result") == "WIN"
        r_value = self._num(outcome.get("realized_r"), 0.0)
        return {
            "source": "signal",
            "direction": outcome.get("direction"),
            "symbol": outcome.get("symbol"),
            "closed_at": int(outcome.get("resolved_at") or outcome.get("opened_at") or 0),
            "opened_at": int(outcome.get("opened_at") or 0),
            "result": outcome.get("final_result"),
            "win": win,
            "r": r_value,
            "timeframe": outcome.get("timeframe"),
            "setup_fingerprint": outcome.get("setup_fingerprint"),
            "regime": outcome.get("regime") or outcome.get("market_phase"),
            "grade": outcome.get("grade"),
            "confidence": outcome.get("confidence"),
        }

    def _manual_timeframe(self, manual):
        payload = (manual.get("payload") or {}) if isinstance(manual.get("payload"), dict) else {}
        return payload.get("timeframe") or "15m"

    def _candles_for_symbol(self, candles, symbol):
        if isinstance(candles, dict):
            return candles.get(symbol) or candles.get("15m") or []
        if not candles:
            return []
        return candles

    def _norm_partial_weights(self, outcome):
        weights = outcome.get("partial_weights")
        if isinstance(weights, (list, tuple)) and weights:
            return [float(w) for w in weights]
        return [1.0, 1.0, 1.0]

    def _weight_for(self, weights, level_no):
        index = level_no - 1
        if 0 <= index < len(weights):
            return float(weights[index])
        return 1.0

    def _signal_partial_weights(self):
        try:
            from config import Config
            raw = str(getattr(Config, "SIGNAL_OUTCOME_PARTIAL_WEIGHTS", "1.0,1.0,1.0"))
            parts = [float(item.strip()) for item in raw.split(",") if item.strip()]
            return parts or [1.0, 1.0, 1.0]
        except Exception:
            return [1.0, 1.0, 1.0]

    def _signal_outcome_expiry_hours(self):
        try:
            from config import Config
            return float(getattr(Config, "SIGNAL_OUTCOME_EXPIRY_HOURS", 72))
        except Exception:
            return 72.0

    def _profit_factor(self, r_values):
        wins_total = sum(v for v in r_values if v > 0)
        losses_total = abs(sum(v for v in r_values if v < 0))
        if losses_total > 0:
            return round(wins_total / losses_total, 4)
        return round(wins_total, 4) if wins_total else 0.0

    def _norm_price(self, value):
        price = self._num(value)
        return price

    def _num(self, value, default=None):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _empty_signal_performance(self):
        return {
            "total": 0, "pending": 0, "closed": 0, "wins": 0, "losses": 0, "partials": 0,
            "expired": 0, "cancelled": 0, "winrate": 0, "expectancy": 0, "profit_factor": 0,
            "average_r": 0, "long": 0, "short": 0, "tp1": 0, "tp2": 0, "tp3": 0, "sl": 0,
        }

    def _empty_manual_performance(self):
        return {
            "total": 0, "wins": 0, "losses": 0, "breakeven": 0, "cancelled": 0, "open": 0,
            "winrate": 0, "expectancy": 0, "profit_factor": 0, "average_r": 0,
        }

    # ------------------------------------------------------------------
    # Signal ID + teorik sinyal sonucu (SIGNAL OUTCOME)
    # ------------------------------------------------------------------

    def generate_signal_id(self, opened_at=None):
        """ATL-YYYYMMDD-SSSSSSS formatında benzersiz sinyal ID üretir.

        Aynı günde üretilen ID'lerin collision yapmaması için mevcut
        signal_outcomes + manual_trades içindeki kullanılmış ID'lerden
        devam sırası seçer (yalnızca bellekte tutulan kayıtlar üzerinden).
        """
        import datetime
        opened_at = int(opened_at or time.time() * 1000)
        day = datetime.datetime.fromtimestamp(opened_at / 1000, tz=datetime.timezone.utc).strftime("%Y%m%d")
        prefix = f"ATL-{day}-"
        used = set()
        for outcome in self._signal_outcomes:
            prefix_str = str(outcome.get("signal_id") or "")
            if prefix_str.startswith(prefix):
                try:
                    used.add(int(prefix_str[len(prefix):]))
                except ValueError:
                    continue
        for manual in self._manual_trades:
            sid = str(manual.get("signal_id") or "")
            if sid.startswith(prefix):
                try:
                    used.add(int(sid[len(prefix):]))
                except ValueError:
                    continue
        counter = max(used, default=0) + 1
        return f"{prefix}{counter:06d}"

    def register_signal_outcome(self, *, symbol, direction, timeframe="15m", entry, stop_loss, tp1=None, tp2=None, tp3=None,
                                rr=None, confidence=None, grade=None, market_phase=None, setup_fingerprint=None,
                                opened_at=None, signal_id=None, payload=None):
        """Yeni sinyal için teorik sonuç takip kaydı oluşturur (PENDING).

        Aynı signal_id zaten kayıtlıysa tekrar eklemez (duplicate koruması).
        """
        expectations = {
            "LONG": (lambda: entry > stop_loss),
            "SHORT": (lambda: entry < stop_loss),
        }
        direction_norm = str(direction or "").upper()
        if direction_norm not in ("LONG", "SHORT"):
            raise ValueError("register_signal_outcome: direction LONG/SHORT olmalı")
        if entry is None or stop_loss is None:
            raise ValueError("register_signal_outcome: entry ve stop_loss zorunlu")

        opened_at = int(opened_at or time.time() * 1000)
        signal_id = signal_id or self.generate_signal_id(opened_at=opened_at)
        if self.find_signal_outcome(signal_id) is not None:
            return self.find_signal_outcome(signal_id)

        tp1 = self._norm_price(tp1)
        tp2 = self._norm_price(tp2)
        tp3 = self._norm_price(tp3)

        outcome = {
            "signal_id": signal_id,
            "symbol": symbol,
            "direction": direction_norm,
            "timeframe": timeframe or "15m",
            "status": "PENDING",
            "opened_at": opened_at,
            "resolved_at": None,
            "entry": self._norm_price(entry),
            "stop_loss": self._norm_price(stop_loss),
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "rr": rr,
            "confidence": confidence,
            "grade": grade,
            "market_phase": market_phase,
            "setup_fingerprint": setup_fingerprint,
            "expiry_hours": self._signal_outcome_expiry_hours(),
            "partial_weights": self._signal_partial_weights(),
            "realized_r": 0.0,
            "max_favorable_excursion": 0.0,
            "max_adverse_excursion": 0.0,
            "hit_tp1": False,
            "hit_tp2": False,
            "hit_tp3": False,
            "hit_sl": False,
            "final_result": None,
            "tps_hit": [],
            "payload": copy.deepcopy(payload or {}),
        }
        self._signal_outcomes.append(outcome)
        self._persist_signal_outcome(outcome)
        return outcome

    def find_signal_outcome(self, signal_id):
        for outcome in self._signal_outcomes:
            if outcome.get("signal_id") == signal_id:
                return outcome
        return None

    def open_signal_outcomes(self, symbol=None):
        out = []
        for outcome in self._signal_outcomes:
            if outcome.get("status") != "PENDING":
                continue
            if symbol and outcome.get("symbol") != symbol:
                continue
            out.append(outcome)
        return out

    def resolved_signal_outcomes(self, symbol=None):
        out = []
        for outcome in self._signal_outcomes:
            if outcome.get("status") == "PENDING":
                continue
            if symbol and outcome.get("symbol") != symbol:
                continue
            out.append(outcome)
        return out
