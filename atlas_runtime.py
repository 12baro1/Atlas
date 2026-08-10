"""Runtime services for Atlas scanner + integration state."""

from __future__ import annotations

import copy
import logging
import os
import threading
import time
from collections import deque
from pathlib import Path

from ai.local_llama_server import LocalLlamaServerManager
from config import Config
from data_engine import exchange, get_correlation_universe, get_market_data
from engine import AtlasEngine
from manual_trade_service import ManualTradeService


class AtlasRuntime:
    """Background scanner runtime that feeds UI without flooding stdout."""

    def __init__(self, symbols=None, logger=None, full_scan=False):
        self.symbols = list(symbols or [])
        self.full_scan = bool(full_scan)
        self.logger = logger or logging.getLogger("atlas.runtime")
        self.engine = AtlasEngine()
        self._stop_event = threading.Event()
        self._thread = None
        self._analysis_lock = threading.Lock()
        self._journal_lock = threading.RLock()
        self.manual_service = ManualTradeService(
            journal=self.engine.trade_journal,
            refresh_learning=self.refresh_learning,
            lock=self._journal_lock,
        )

        self._lock = threading.Lock()
        self._current_signal = None
        self._current_symbol = self.symbols[0] if self.symbols else None
        self._last_results = []
        self._latest_analysis_by_symbol = {}
        self._market_symbols = None
        self._scanner_stats = {
            "processed": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "cycle": 0,
            "started_at": int(time.time() * 1000),
            "last_update_ms": None,
            "status": "READY",
            "mode": "FULL_SCAN" if self.full_scan else "MANUAL_ANALYSIS",
        }

        self._logs = deque(maxlen=500)
        self._error = None
        self._telegram_service = None
        self._llama_manager = LocalLlamaServerManager(
            repo_root=Path(__file__).resolve().parent,
            config=Config,
        )
        self._ai_state = {
            "provider": str(getattr(Config, "AI_PROVIDER", "openai_compat") or "openai_compat"),
            "status": "UNKNOWN",
            "detail": "",
            "base_url": self._llama_manager.base_url,
            "owner": "none",
        }

        with self._journal_lock:
            perf = self.engine.trade_journal.manual_trade_performance()
        self._boot_summary = {
            "open_manual": int(perf.get("open", 0)),
            "closed_manual": int(perf.get("total", 0)),
            "not_traded": int(perf.get("not_traded", 0)),
        }

    def start(self, daemon=True):
        if self.full_scan and self.symbols:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._loop, daemon=daemon)
            self._thread.start()
            return
        self._set_status("READY")

    def stop(self, timeout=5.0):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        if self._telegram_service is not None:
            try:
                self._telegram_service.stop()
            except Exception:
                pass
        try:
            self.engine.flush_telegram_notifications(
                join_timeout=float(getattr(Config, "TELEGRAM_ASYNC_FLUSH_TIMEOUT_SECONDS", 0.5))
            )
        except Exception:
            pass
        try:
            self._llama_manager.stop_if_owned()
        except Exception:
            pass

    def boot_summary(self):
        return dict(self._boot_summary)

    def initialize_ai(self):
        provider = str(getattr(Config, "AI_PROVIDER", "openai_compat") or "openai_compat").strip().lower()
        self._ai_state["provider"] = provider
        self._ai_state["base_url"] = self._llama_manager.base_url

        if provider != "local":
            self._ai_state["status"] = "REMOTE"
            self._ai_state["detail"] = "provider_not_local"
            self._ai_state["owner"] = "none"
            return dict(self._ai_state)

        status = self._llama_manager.status()
        if status.online:
            self._ai_state["status"] = "ONLINE"
            self._ai_state["detail"] = status.detail
            self._ai_state["owner"] = status.owner
            return dict(self._ai_state)

        self._ai_state["status"] = "STARTING"
        self._ai_state["detail"] = "Local AI baslatiliyor..."
        timeout_seconds = float(getattr(Config, "AI_LOCAL_START_TIMEOUT_SECONDS", 180) or 180)
        started = self._llama_manager.ensure_running(timeout_seconds=timeout_seconds)
        if started.online:
            self._ai_state["status"] = "ONLINE"
            self._ai_state["detail"] = started.detail
            self._ai_state["owner"] = started.owner
        else:
            self._ai_state["status"] = "OFFLINE"
            self._ai_state["detail"] = started.detail
            self._ai_state["owner"] = started.owner
        return dict(self._ai_state)

    def ai_status(self):
        provider = str(getattr(Config, "AI_PROVIDER", "openai_compat") or "openai_compat").strip().lower()
        self._ai_state["provider"] = provider
        self._ai_state["base_url"] = self._llama_manager.base_url

        if provider != "local":
            current = dict(self._ai_state)
            if current.get("status") == "UNKNOWN":
                current["status"] = "REMOTE"
                current["detail"] = "provider_not_local"
            return current

        current = self._llama_manager.status()
        if current.online:
            self._ai_state["status"] = "ONLINE"
            self._ai_state["detail"] = current.detail
            self._ai_state["owner"] = current.owner
        elif self._ai_state.get("status") not in {"STARTING", "OFFLINE"}:
            self._ai_state["status"] = "OFFLINE"
            self._ai_state["detail"] = current.detail
            self._ai_state["owner"] = current.owner
        return dict(self._ai_state)

    def attach_telegram_service(self, service):
        self._telegram_service = service

    def set_symbols(self, symbols):
        with self._lock:
            self.symbols = list(symbols or [])

    def current_symbol(self):
        with self._lock:
            return self._current_symbol

    def latest_analysis(self, symbol=None):
        target = self.normalize_symbol(symbol) if symbol else None
        with self._lock:
            if target:
                return self._latest_analysis_by_symbol.get(target)
            if self._current_symbol:
                cached = self._latest_analysis_by_symbol.get(self._current_symbol)
                if cached is not None:
                    return cached
            if self._latest_analysis_by_symbol:
                latest_symbol = next(reversed(self._latest_analysis_by_symbol))
                return self._latest_analysis_by_symbol.get(latest_symbol)
            return None

    def _ensure_market_symbols(self):
        if self._market_symbols is not None:
            return self._market_symbols
        try:
            markets = exchange.load_markets()
            self._market_symbols = set((markets or {}).keys())
        except Exception:
            self._market_symbols = set()
        return self._market_symbols

    def symbol_exists(self, symbol):
        normalized = self.normalize_symbol(symbol)
        if not normalized:
            return False
        known = self._ensure_market_symbols()
        if not known:
            return True
        return normalized in known

    def normalize_symbol(self, raw_symbol):
        text = str(raw_symbol or "").strip().upper()
        if not text:
            return None
        text = text.replace(" ", "")
        if "/" in text and ":" in text:
            return text
        if "/" in text and ":" not in text:
            left, right = text.split("/", 1)
            right = right.strip()
            if right == "USDT":
                return f"{left}/USDT:USDT"
            return text
        if text.endswith(":USDT") and "/" not in text:
            base = text[:-5]
            if base:
                return f"{base}/USDT:USDT"
        if text.endswith("USDT") and "/" not in text and len(text) > 4:
            base = text[:-4]
            return f"{base}/USDT:USDT"
        if text.isalpha() and 2 <= len(text) <= 12:
            return f"{text}/USDT:USDT"
        return text

    def analyze_symbol(self, raw_symbol, force_refresh=False):
        self._set_status("ANALYZING")
        try:
            return self._analyze_symbol(raw_symbol, force_refresh=force_refresh, from_scan=False)
        finally:
            self._set_status("READY")

    def snapshot(self):
        with self._lock:
            return {
                "scanner": dict(self._scanner_stats),
                "mode": self._scanner_stats.get("mode", "MANUAL_ANALYSIS"),
                "current_symbol": self._current_symbol,
                "current_signal": self._current_signal,
                "recent": list(self._last_results),
                "error": self._error,
            }

    def telegram_status(self):
        token = str(getattr(Config, "TELEGRAM_BOT_TOKEN", "") or "").strip()
        return {
            "connected": bool(token),
            "polling_enabled": bool(getattr(Config, "TELEGRAM_POLLING_ENABLED", True)),
            "webhook_enabled": bool(getattr(Config, "TELEGRAM_WEBHOOK_ENABLED", False)),
            "service_running": self._telegram_service is not None and not self._telegram_service.stop_flag.is_set(),
            "last_signal": (self._current_signal or {}).get("signal_id") if isinstance(self._current_signal, dict) else None,
            "last_message": (self._current_signal or {}).get("symbol") if isinstance(self._current_signal, dict) else None,
            "last_error": self._error,
        }

    def current_signal(self):
        with self._lock:
            return copy.deepcopy(self._current_signal)

    def learning_panel(self):
        with self._journal_lock:
            manual_perf = self.engine.trade_journal.manual_trade_performance()
            learning_stats = self.engine.learning.stats

        source = learning_stats.get("source")
        feed_meta = learning_stats.get("feed_meta") or {}
        index = learning_stats.get("index") or {}
        exact = index.get("exact") or {}
        matched_setups = sum(1 for payload in exact.values() if int(payload.get("total", 0)) > 0)

        historical_edge = 0.0
        reliability = 0.0
        adjustment = 0.0
        if exact:
            total = len(exact)
            historical_edge = sum(float(item.get("average_r") or 0.0) for item in exact.values()) / max(total, 1)
            reliability = sum(float(item.get("reliability") or 0.0) for item in exact.values()) / max(total, 1)
            adjustment = sum(float(item.get("weight") or 1.0) - 1.0 for item in exact.values()) / max(total, 1)

        return {
            "source": source,
            "closed_manual_trades": int(manual_perf.get("total", 0)),
            "wins": int(manual_perf.get("wins", 0)),
            "losses": int(manual_perf.get("losses", 0)),
            "win_rate": float(manual_perf.get("winrate", 0.0)),
            "average_r": float(manual_perf.get("average_r", 0.0)),
            "expectancy": float(manual_perf.get("expectancy", 0.0)),
            "profit_factor": float(manual_perf.get("profit_factor", 0.0)),
            "historical_edge": round(historical_edge, 4),
            "reliability": round(reliability, 4),
            "matched_setups": matched_setups,
            "learning_adjustment": round(adjustment, 4),
            "open_manual": int(manual_perf.get("open", 0)),
            "not_traded": int(manual_perf.get("not_traded", 0)),
            "feed_meta": feed_meta,
        }

    def journal_summary(self):
        with self._journal_lock:
            recent_manual = self.engine.trade_journal.manual_trades(limit=200)
        return recent_manual

    def manual_trades(self, *, limit=200, status=None, symbol=None):
        with self._journal_lock:
            return list(
                self.engine.trade_journal.manual_trades(
                    limit=limit,
                    status=status,
                    symbol=symbol,
                )
            )

    def open_manual_trades(self, symbol=None):
        with self._journal_lock:
            return list(self.engine.trade_journal.open_manual_trades(symbol=symbol))

    def signal_performance(self):
        with self._journal_lock:
            return dict(self.engine.trade_journal.signal_performance())

    def manual_performance(self):
        with self._journal_lock:
            return dict(self.engine.trade_journal.manual_trade_performance())

    def signal_outcomes(self, *, limit=400, status=None, symbol=None):
        with self._journal_lock:
            return list(
                self.engine.trade_journal.signal_outcomes(
                    limit=limit,
                    status=status,
                    symbol=symbol,
                )
            )

    def manual_trade_for(self, signal_id):
        with self._journal_lock:
            return self.engine.trade_journal.find_manual_trade(signal_id=signal_id)

    def logs(self):
        return list(self._logs)

    def refresh_learning(self):
        with self._journal_lock:
            return self.engine.refresh_learning()

    def learning_stats(self):
        with self._journal_lock:
            return copy.deepcopy(self.engine.learning.stats)

    def learning_records(self, source="manual", symbol=None, as_of_ms=None):
        with self._journal_lock:
            return list(
                self.engine.trade_journal.learning_records(
                    source=source,
                    symbol=symbol,
                    as_of_ms=as_of_ms,
                )
            )

    def setup_statistics(self):
        with self._journal_lock:
            return dict(self.engine.trade_journal.setup_statistics())

    def analysis_summary(self):
        with self._journal_lock:
            return dict(self.engine.trade_journal.analysis_summary())

    def _loop(self):
        interval = float(getattr(Config, "ATLAS_SCAN_INTERVAL_SECONDS", 0) if hasattr(Config, "ATLAS_SCAN_INTERVAL_SECONDS") else 0)
        if interval <= 0:
            interval = float(os.getenv("ATLAS_SCAN_INTERVAL_SECONDS", "900") or 900)

        while not self._stop_event.is_set():
            cycle_started = time.perf_counter()
            self._set_status("RUNNING")
            self._inc("cycle")
            self._scan_cycle()
            self._set_status("SLEEP")
            elapsed = time.perf_counter() - cycle_started
            wait_time = max(0.0, interval - elapsed)
            if self._stop_event.wait(wait_time):
                break
        self._set_status("STOPPED")

    def _scan_cycle(self):
        for index, symbol in enumerate(self.symbols, start=1):
            if self._stop_event.is_set():
                return
            self._analyze_symbol(symbol, force_refresh=False, from_scan=True, scan_index=index, scan_total=len(self.symbols))

    def _analyze_symbol(self, raw_symbol, force_refresh=False, from_scan=False, scan_index=None, scan_total=None):
        symbol = self.normalize_symbol(raw_symbol)
        if not symbol:
            return {"ok": False, "error": "symbol_required"}

        with self._lock:
            self._current_symbol = symbol
        self._inc("processed")
        started = int(time.time() * 1000)

        try:
            if not self.symbol_exists(symbol):
                self._inc("skipped")
                return {"ok": False, "symbol": symbol, "error": "symbol_not_found"}

            try:
                universe = get_correlation_universe(force_refresh=force_refresh)
            except Exception as exc:
                universe = {}
                self._log(f"WARN correlation universe unavailable: {exc}")

            with self._analysis_lock:
                data = get_market_data(symbol, force_refresh=force_refresh)
                if universe:
                    data["correlation_universe"] = universe

                with self._journal_lock:
                    result = self.engine.analyze(data)
                    if result is None:
                        self._inc("skipped")
                        return {"ok": False, "symbol": symbol, "error": "no_result"}

                    self._inc("success")
                    self._register_result(result)
                    self._latest_analysis_by_symbol[symbol] = result

                    if Config.SIGNAL_TRACKING_ENABLED:
                        candles_15m = data.get("15m") or data.get("15M") or []
                        self.engine.trade_journal.resolve_signal_outcomes({symbol: candles_15m})

            if from_scan:
                self._log(f"[{scan_index}/{scan_total}] analyzed {symbol}")
            else:
                self._log(f"Analyzed {symbol}")

            return {
                "ok": True,
                "symbol": symbol,
                "result": result,
                "elapsed_ms": int(time.time() * 1000) - started,
            }
        except Exception as exc:
            self._inc("failed")
            self._error = str(exc)
            self._log(f"ERROR {symbol}: {exc}")
            return {
                "ok": False,
                "symbol": symbol,
                "error": str(exc),
                "elapsed_ms": int(time.time() * 1000) - started,
            }
        finally:
            with self._lock:
                self._scanner_stats["last_update_ms"] = int(time.time() * 1000)

    def _register_result(self, result):
        signal = result.get("signal") or {}
        risk = result.get("risk") or {}
        decision = result.get("decision") or {}
        analysis = result.get("analysis") or {}
        setup_quality = analysis.get("setup_quality") or {}
        learning = setup_quality.get("learning") or signal.get("learning") or {}

        manual_quality = {}
        try:
            manual_quality = self.engine.manual_quality_gate.evaluate(
                symbol=result.get("symbol", "UNKNOWN"),
                signal=signal,
                entry=analysis.get("entry") or {},
                risk=risk,
                decision=decision,
                confluence=analysis.get("confluence") or {},
                market_phase=analysis.get("market_phase") or {},
                trade_journal=self.engine.trade_journal,
            )
        except Exception:
            manual_quality = {}

        signal_id = self._resolve_signal_id(result)
        manual_trade = self.manual_trade_for(signal_id) if signal_id else None
        item = {
            "signal_id": signal_id,
            "symbol": result.get("symbol"),
            "direction": signal.get("signal"),
            "entry": risk.get("entry"),
            "stop_loss": risk.get("stop_loss"),
            "tp1": risk.get("tp1"),
            "tp2": risk.get("tp2"),
            "tp3": risk.get("tp3"),
            "rr": risk.get("selected_rr") if risk.get("selected_rr") is not None else risk.get("rr"),
            "confidence": signal.get("confidence"),
            "grade": signal.get("grade"),
            "decision": decision.get("action"),
            "manual_score": manual_quality.get("score"),
            "setup_fingerprint": setup_quality.get("setup_fingerprint"),
            "market_phase": (analysis.get("market_phase") or {}).get("phase"),
            "historical_edge": learning.get("historical_edge") if isinstance(learning, dict) else None,
            "reliability": learning.get("reliability") if isinstance(learning, dict) else None,
            "expected_r": learning.get("expected_r") if isinstance(learning, dict) else None,
            "learning_adjustment": learning.get("score_delta") if isinstance(learning, dict) else None,
            "setup_quality": setup_quality.get("score"),
            "manual_status": (manual_trade or {}).get("status"),
            "manual_result": (manual_trade or {}).get("result"),
            "timestamp": int(time.time() * 1000),
        }
        with self._lock:
            self._current_signal = item
            self._last_results.append(item)
            self._last_results = self._last_results[-250:]
            self._scanner_stats["last_update_ms"] = item["timestamp"]

    def _resolve_signal_id(self, result):
        symbol = result.get("symbol")
        direction = (result.get("signal") or {}).get("signal")
        with self._journal_lock:
            outcomes = self.engine.trade_journal.signal_outcomes(symbol=symbol, limit=30)

        pending = [item for item in outcomes if item.get("status") == "PENDING"]
        if pending:
            outcomes = pending
        for outcome in outcomes:
            if outcome.get("direction") == direction:
                return outcome.get("signal_id")
        return None

    def _set_status(self, status):
        with self._lock:
            self._scanner_stats["status"] = status

    def _inc(self, key):
        with self._lock:
            self._scanner_stats[key] = int(self._scanner_stats.get(key, 0)) + 1

    def _log(self, message):
        timestamp = time.strftime("%H:%M:%S", time.localtime())
        self._logs.append(f"{timestamp} {message}")
