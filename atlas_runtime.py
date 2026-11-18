"""Runtime services for Atlas scanner + integration state."""

from __future__ import annotations

import copy
import logging
import math
import os
import threading
import traceback
import time
from collections import defaultdict, deque
from typing import Any, Dict, Optional
from config import Config
from data_engine import exchange, get_correlation_universe, get_market_data, get_smt_universe
from engine import AtlasEngine
from strategy_outcome_journal import StrategyOutcomeJournal
from manual_trade_service import ManualTradeService
from opportunity_pool import get_opportunity_pool, SetupCandidate

def _is_fresh_15m_data(candles, now_ms, max_age_seconds):
    """Return False for absent, future, or stale last-closed 15m candles."""
    if not candles:
        return False
    try:
        latest_close_ms = int(candles[-1].time) + 15 * 60 * 1000
        age_ms = int(now_ms) - latest_close_ms
        max_age_ms = max(0, int(float(max_age_seconds) * 1000))
    except (AttributeError, TypeError, ValueError, OverflowError):
        return False
    return 0 <= age_ms <= max_age_ms



class AtlasRuntime:
    """Background scanner runtime that feeds UI without flooding stdout."""

    def __init__(self, symbols=None, logger=None, full_scan=False):
        self.symbols = list(symbols or [])
        self.full_scan = bool(full_scan)
        self.logger = logger or logging.getLogger("atlas.runtime")
        self.engine = AtlasEngine()
        self.strategy_outcome_journal = StrategyOutcomeJournal()
        self._stop_event = threading.Event()
        self._thread = None
        # Per-symbol locks to allow parallel analysis of different symbols
        # while protecting AtlasMainEngine.evidence_pool for the same symbol.
        self._analysis_locks = {}
        self._analysis_locks_lock = threading.Lock()
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
        self._latest_analysis_at = {}
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
        self._ai_state = {"provider": "disabled", "status": "DISABLED", "detail": "AI is not part of terminal Atlas."}
        # Production telemetry (requirement H): strategy generation funnel.
        self._strategy_telemetry = {
            "analyses": 0,
            "raw_setups_generated": 0,
            "common_filter_passed": 0,
            "common_filter_rejected": 0,
            "rejection_reasons": defaultdict(int),
            "per_strategy": defaultdict(lambda: {
                "setups": 0, "passed": 0, "rejected": 0, "selected": 0,
                "no_setup": 0, "condition_not_met": 0, "missing_data": 0,
                "insufficient_history": 0, "errors": 0, "other_no_setup": 0,
                "reason_counts": defaultdict(int),
            }),
        }
        # Scan infrastructure: Gate.io inventory, durable queue, background
        # workers and the 00:00 Istanbul daily refresh. All independent of
        # the Telegram service lifecycle.
        from market_inventory import get_market_inventory
        from scan_queue import ScanQueue
        from scan_service import ScanService
        from daily_refresh import DailyPoolRefresh
        self._market_inventory = get_market_inventory(exchange=exchange)
        self._scan_queue = ScanQueue()
        self._scan_service = ScanService(
            runtime=self, queue=self._scan_queue, inventory=self._market_inventory
        )
        self._daily_refresh = DailyPoolRefresh(
            pool=self._opportunity_pool(),
            scan_queue=self._scan_queue,
            market_inventory=self._market_inventory,
        )

        with self._journal_lock:
            perf = self.engine.trade_journal.manual_trade_performance()
        self._boot_summary = {
            "open_manual": int(perf.get("open", 0)),
            "closed_manual": int(perf.get("total", 0)),
            "not_traded": int(perf.get("not_traded", 0)),
        }

    def start(self, daemon=True):
        # Scan infrastructure resumes regardless of who started the runtime:
        # pending queue work continues and the daily refresh stays scheduled.
        try:
            # Preserve oversized historical queue generations, but resume work
            # only from a fresh top-300 generation to avoid repeating the old
            # 1,000+ market backlog after deployment.
            self._scan_service.enforce_universe_limit()
            ranking_sync = self._scan_service.synchronize_ranked_universe(limit=300)
            self.logger.info(
                "Active scan universe synchronized | selected=%s ranking=%s rebuilt=%s",
                ranking_sync.get("selected", 0),
                ranking_sync.get("ranking_source", "unknown"),
                ranking_sync.get("rebuilt", False),
            )
            self._scan_service.ensure_workers()
            self._daily_refresh.start_background()
        except Exception as exc:
            self.logger.error(f"Scan infrastructure startup failed: {exc}")
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
        try:
            if getattr(self, "_scan_service", None) is not None:
                self._scan_service.stop_scan(timeout_seconds=timeout)
        except Exception:
            pass
        try:
            if getattr(self, "_scan_queue", None) is not None:
                self._scan_queue.close()
        except Exception:
            pass
        try:
            if getattr(self, "_daily_refresh", None) is not None:
                self._daily_refresh.stop(timeout=timeout)
        except Exception:
            pass
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

    def _get_analysis_lock(self, symbol):
        """Get or create a per-symbol lock for analysis."""
        with self._analysis_locks_lock:
            lock = self._analysis_locks.get(symbol)
            if lock is None:
                lock = threading.Lock()
                self._analysis_locks[symbol] = lock
            return lock


    def boot_summary(self):
        return dict(self._boot_summary)

    def initialize_ai(self):
        """Compatibility stub: AI inference is deliberately removed from Atlas."""
        return dict(self._ai_state)

    def ai_status(self):
        """Compatibility stub: no local or remote model is started."""
        return dict(self._ai_state)

    def attach_telegram_service(self, service):
        self._telegram_service = service

    def _opportunity_pool(self):
        return get_opportunity_pool()

    # ------------------------------------------------------------------
    # Scan service facade (Telegram-independent, requirement F)
    # ------------------------------------------------------------------

    def start_scan(self, limit=None):
        """Enqueue a scan of the Gate.io universe and ensure workers run."""
        return self._scan_service.start_scan(limit)

    def stop_scan(self):
        return self._scan_service.stop_scan()

    def scan_status(self):
        status = self._scan_service.status()
        # Queue progress alone cannot explain an empty setup pool. Expose the
        # seven-strategy generation funnel and validated pool alongside it.
        status["strategy_telemetry"] = self.strategy_telemetry()
        status["pool"] = self._opportunity_pool().get_stats()
        return status

    def refresh_market_inventory(self):
        """Force a Gate.io inventory refresh (rate-limit aware).

        A user-initiated refresh always attempts a real refresh; the TTL only
        throttles automatic checks, never an explicit request.
        """
        return self._market_inventory.refresh(force=True)

    def resume_scan(self):
        """Resume pending queue work without adding anything new."""
        self._scan_service.ensure_workers()
        return self._scan_service.status()

    def strategy_telemetry(self):
        with self._lock:
            return self._strategy_telemetry_locked()

    def _strategy_telemetry_locked(self):
        per_strategy = {}
        for strategy_id, raw_counts in self._strategy_telemetry["per_strategy"].items():
            counts = {
                key: value for key, value in raw_counts.items()
                if key != "reason_counts"
            }
            reason_counts = raw_counts.get("reason_counts") or {}
            counts["top_reasons"] = [
                {"reason": reason, "count": count}
                for reason, count in sorted(
                    reason_counts.items(), key=lambda item: (-item[1], item[0])
                )[:2]
            ]
            per_strategy[strategy_id] = counts
        return {
            "analyses": self._strategy_telemetry["analyses"],
            "raw_setups_generated": self._strategy_telemetry["raw_setups_generated"],
            "common_filter_passed": self._strategy_telemetry["common_filter_passed"],
            "common_filter_rejected": self._strategy_telemetry["common_filter_rejected"],
            "rejection_reasons": dict(self._strategy_telemetry["rejection_reasons"]),
            "per_strategy": per_strategy,
        }

    @property
    def scanner(self):
        """Return the engine's scanner with thread-safe access."""
        return self.engine.scanner

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

    def _prune_latest_analyses(self, now_ms=None):
        """Remove stale cache entries and enforce a deterministic symbol cap."""
        now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
        max_age_ms = max(0, int(float(getattr(Config, "ANALYSIS_CACHE_MAX_AGE_SECONDS", 86400)) * 1000))
        max_symbols = max(1, int(getattr(Config, "ANALYSIS_CACHE_MAX_SYMBOLS", 1100)))
        with self._lock:
            stale = [
                symbol for symbol, analyzed_at in self._latest_analysis_at.items()
                if not analyzed_at or now_ms - int(analyzed_at) > max_age_ms
            ]
            for symbol in stale:
                self._latest_analysis_at.pop(symbol, None)
                self._latest_analysis_by_symbol.pop(symbol, None)

            if len(self._latest_analysis_by_symbol) > max_symbols:
                oldest_first = sorted(
                    self._latest_analysis_at,
                    key=lambda symbol: int(self._latest_analysis_at.get(symbol) or 0),
                )
                for symbol in oldest_first[:len(self._latest_analysis_by_symbol) - max_symbols]:
                    self._latest_analysis_at.pop(symbol, None)
                    self._latest_analysis_by_symbol.pop(symbol, None)

    def latest_analyses(self, max_age_seconds=None):
        """Return a snapshot of cached analyses, optionally excluding stale entries."""
        now_ms = int(time.time() * 1000)
        self._prune_latest_analyses(now_ms)
        max_age_ms = None if max_age_seconds is None else max(0, int(float(max_age_seconds) * 1000))
        with self._lock:
            items = []
            for symbol, result in self._latest_analysis_by_symbol.items():
                analyzed_at = int(self._latest_analysis_at.get(symbol) or 0)
                if max_age_ms is not None and (not analyzed_at or now_ms - analyzed_at > max_age_ms):
                    continue
                items.append({
                    "symbol": symbol,
                    "result": copy.deepcopy(result),
                    "analyzed_at_ms": analyzed_at,
                })
            return items

    def track_requested_result(self, result):
        """Track a cached setup only after a Telegram command explicitly requests it."""
        if not isinstance(result, dict):
            return None
        signal = result.get("signal") or {}
        decision = result.get("decision") or {}
        if (
            signal.get("signal") not in {"LONG", "SHORT"}
            or decision.get("action") not in {"EXECUTE", "EXECUTE_WITH_CAUTION"}
        ):
            return None
        if not bool(getattr(Config, "SIGNAL_TRACKING_ENABLED", True)):
            return None
        with self._journal_lock:
            return self.engine._register_tracked_signal(
                result.get("symbol") or "UNKNOWN",
                result,
            )

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

    def analyze_symbol(self, raw_symbol, force_refresh=False, track_signal=False, use_websocket=True):
        """Analyze one symbol; journal tracking is opt-in for explicit trade requests."""
        self._set_status("ANALYZING")
        try:
            return self._analyze_symbol(raw_symbol, force_refresh=force_refresh, from_scan=False, track_signal=track_signal, use_websocket=use_websocket)
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
                "scan_queue": self._scan_service.status() if getattr(self, "_scan_service", None) else None,
                "strategy_telemetry": self._strategy_telemetry_locked() if hasattr(self, "_strategy_telemetry") else None,
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
            "learning_adjustment": round(adjustment, 2),
            "records_fed": int((learning_stats.get("meta") or {}).get("records_fed", 0)),
            "buckets": int((learning_stats.get("meta") or {}).get("buckets", 0)),
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

    def strategy_performance(self, symbol=None, regime=None):
        """Return independently aggregated, cost-adjusted IS/OOS results per strategy."""
        return self.strategy_outcome_journal.performance_snapshot(
            symbol=symbol,
            regime=regime,
            source_revision=self.strategy_outcome_journal.current_revision(),
        )

    def record_strategy_outcome(self, **outcome):
        """Persist a closed strategy outcome; callers must supply cost-adjusted net R."""
        return self.strategy_outcome_journal.record_outcome(**outcome)

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
        """Run symbol analysis in parallel with controlled concurrency."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # Limit concurrent analyses to avoid overwhelming the API
        max_workers = int(getattr(Config, "SCAN_MAX_WORKERS", "4") or "4")
        max_workers = max(1, min(max_workers, len(self.symbols)))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self._analyze_symbol,
                    symbol,
                    False,
                    True,
                    idx,
                    len(self.symbols),
                ): symbol
                for idx, symbol in enumerate(self.symbols, start=1)
            }

            for future in as_completed(futures):
                if self._stop_event.is_set():
                    # Cancel remaining futures
                    for f in futures:
                        f.cancel()
                    return
                try:
                    future.result()
                except Exception as exc:
                    symbol = futures[future]
                    self._log(f"ERROR {symbol} (parallel): {exc}")

        # Expire only after the cycle had a chance to process the latest candles.
        # This also handles stale symbols that produced no fresh candle.
        with self._journal_lock:
            self.engine.trade_journal.expire_stale_signal_outcomes()

    def _analyze_symbol(self, raw_symbol, force_refresh=False, from_scan=False, scan_index=None, scan_total=None, track_signal=None, use_websocket=True):
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

            lock = self._get_analysis_lock(symbol)
            with lock:
                data = get_market_data(symbol, force_refresh=force_refresh, use_websocket=bool(use_websocket and not from_scan))
                # Never base live SMC confirmation on a still-forming 15m candle.
                # Backtests use historical candles and do not pass through this live-runtime filter.
                from timing import closed_htf_candles
                now_ms = int(time.time() * 1000)
                candles_15m = data.get("15m") or data.get("15M") or []
                closed_15m = closed_htf_candles(candles_15m, now_ms, "15m")
                if not closed_15m:
                    self._inc("skipped")
                    self._log(f"WAIT {symbol}: no fully closed 15m candle available")
                    return {"ok": False, "symbol": symbol, "error": "no_closed_15m_candle"}
                max_age_seconds = getattr(Config, "MAX_15M_CANDLE_AGE_SECONDS", 1800)
                if not _is_fresh_15m_data(closed_15m, now_ms, max_age_seconds):
                    self._inc("skipped")
                    latest_close_ms = closed_15m[-1].time + 15 * 60 * 1000
                    age_seconds = max(0, (now_ms - latest_close_ms) / 1000)
                    self._log(
                        f"WAIT {symbol}: stale 15m market data "
                        f"(age={age_seconds:.0f}s max={float(max_age_seconds):.0f}s)"
                    )
                    return {
                        "ok": False,
                        "symbol": symbol,
                        "error": "stale_15m_market_data",
                        "age_seconds": age_seconds,
                    }
                data = dict(data)
                data["15m"] = closed_15m
                if universe:
                    data["correlation_universe"] = universe
                try:
                    smt_universe = get_smt_universe(force_refresh=force_refresh)
                    if smt_universe:
                        data["smt_universe"] = smt_universe
                except Exception as exc:
                    self._log(f"WARN SMT comparison universe unavailable: {exc}")

                # Runtime adds closed-candle, BTC/ETH correlation and SMT data
                # after DataEngine's initial snapshot; rebuild the shared
                # evidence only after the complete analysis input is assembled.
                from shared.market_data_services import build_shared_market_evidence
                data["shared_market_evidence"] = build_shared_market_evidence(data)

                pool = get_opportunity_pool()
                with self._journal_lock:
                    should_track_signal = (not from_scan) if track_signal is None else bool(track_signal)
                    result = self.engine.analyze(data, track_signal=should_track_signal)
                    # AtlasEngine already ran the seven generators, common filter,
                    # and final selector before recording this result.
                    if result is None:
                        self._inc("skipped")
                        return {"ok": False, "symbol": symbol, "error": "no_result"}
                    self._inc("success")
                    
                    # Invalidate an unaccepted setup only when its OWN strategy
                    # completed a fresh evaluation and explicitly reports that
                    # its native setup conditions are no longer present.
                    strategy_lab = result.get("strategy_lab") or {}
                    diagnostics = strategy_lab.get("diagnostics") or {}
                    invalidated_setups = []
                    for strategy_row in diagnostics.get("strategies") or []:
                        strategy_id = str(strategy_row.get("strategy_id") or "").strip()
                        status = str(strategy_row.get("status") or "").upper()
                        if not strategy_id or status not in {"NO_SETUP", "CONDITION_NOT_MET"}:
                            continue
                        removed = pool.invalidate_strategy_setup(
                            symbol, strategy_id, "STRATEGY_STRUCTURE_BROKEN"
                        )
                        invalidated_setups.extend({
                            "setup_id": item.setup_id,
                            "symbol": item.symbol,
                            "strategy_id": item.strategy_id,
                            "strategy_name": item.strategy_name,
                            "direction": item.direction,
                        } for item in removed)

                    # Add/refresh the selected setup after invalidating broken
                    # strategy structures; other strategies remain independent.
                    self._register_result(result)
                    self._accumulate_strategy_telemetry(result)
                    if invalidated_setups:
                        result["invalidated_pool_setups"] = invalidated_setups
                    with self._lock:
                        self._latest_analysis_by_symbol[symbol] = result
                        self._latest_analysis_at[symbol] = int(time.time() * 1000)
                    self._prune_latest_analyses()

                    # The selected setup lives in strategy_lab; there is no
                    # top-level "selected" key on the engine result payload.
                    strategy_lab = result.get("strategy_lab") or {}
                    selected = strategy_lab.get("selected")
                    if isinstance(selected, dict):
                        try:
                            analysis = result.get("analysis") or {}
                            candidate = self._setup_to_candidate(
                                selected,
                                symbol,
                                trace_id=result.get("trace_id"),
                                regime=strategy_lab.get("regime"),
                                market_phase=(analysis.get("market_phase") or {}).get("phase"),
                            )
                            if candidate:
                                pool.add_candidate(candidate)
                                # Validate to move from candidates to validated pool
                                pool.validate_candidate(candidate.setup_id)
                                self.logger.debug(
                                    "Added and validated candidate from %s: %s",
                                    symbol, candidate.setup_id,
                                )
                            else:
                                self.logger.debug(
                                    "Selected setup for %s rejected by candidate validation",
                                    symbol,
                                )
                        except Exception as e:
                            self.logger.warning(
                                "Failed to add candidate from %s to pool: %s", symbol, e
                            )

                    if Config.SIGNAL_TRACKING_ENABLED:
                        candles_15m = data.get("15m") or data.get("15M") or []
                        resolved_outcomes = self.engine.trade_journal.resolve_signal_outcomes(
                            {symbol: candles_15m}
                        )
                        # Kapanan sinyal sonuçları aynı tarama döngüsünde öğrenme
                        # indeksine aktarılır; bir sonraki analiz eski istatistikle kalmaz.
                        if resolved_outcomes:
                            self.engine.refresh_learning()

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
            error_trace = traceback.format_exc()
            self._error = error_trace
            self._log(f"ERROR {symbol}: {error_trace}")
            return {
                "ok": False,
                "symbol": symbol,
                "error": error_trace,
                "elapsed_ms": int(time.time() * 1000) - started,
            }
        finally:
            with self._lock:
                self._scanner_stats["last_update_ms"] = int(time.time() * 1000)

    def _resolve_signal_id(self, result):
        """Resolve the journal outcome linked to an analysis result.

        Prefer an ID already attached to the result. Otherwise resolve only
        actionable LONG/SHORT outcomes through the shared manual trade service.
        Missing/non-actionable results intentionally have no signal ID.
        """
        if not isinstance(result, dict):
            return None

        journal = result.get("journal")
        signal_id = result.get("signal_id")
        if not signal_id and isinstance(journal, dict):
            signal_id = journal.get("signal_id")
        if signal_id:
            return str(signal_id)

        signal = result.get("signal")
        signal = signal if isinstance(signal, dict) else {}
        direction = str(signal.get("signal") or "").strip().upper()
        symbol = str(result.get("symbol") or "").strip()
        if not symbol or direction not in {"LONG", "SHORT"}:
            return None

        try:
            with self._journal_lock:
                return self.manual_service.resolve_signal_id(
                    symbol=symbol,
                    direction=direction,
                )
        except Exception:
            self.logger.exception(
                "Signal ID resolution failed | symbol=%s direction=%s",
                symbol,
                direction,
            )
            return None

    def invalidate_setup(self, setup_id: str, reason: str) -> bool:
        """Remove an invalid setup from the opportunity pool and symbol state.

        Clearing the persisted active snapshot is essential: otherwise a
        removed setup could be restored on the next analysis and prevent the
        newly selected setup from becoming the active snapshot. This does not
        blacklist the symbol or alter the scan queue.
        """
        pool = self._opportunity_pool()
        candidate = pool.get_setup(setup_id)
        if candidate is None:
            return False
        removed = pool.invalidate_setup(setup_id, reason)
        if not removed:
            return False

        state_engine = getattr(self.engine, "state_engine", None)
        if state_engine is not None:
            state_engine.clear_active_setup(
                candidate.symbol, reason=f"setup_invalidated:{reason}"
            )
        return True

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

    def _setup_to_candidate(
        self,
        selected: Dict[str, Any],
        symbol: str,
        trace_id: Optional[str] = None,
        regime: Optional[str] = None,
        market_phase: Optional[str] = None,
    ) -> Optional[SetupCandidate]:
        """Convert a selected strategy setup into a SetupCandidate.

        Geometry rules (release blocker):
        - risk   = abs(entry - stop_loss)
        - reward = abs(tp - entry) for every TP (reward measured from entry,
          never from the stop)
        - LONG  requires stop < entry < tp1 < tp2 < tp3
        - SHORT requires stop > entry > tp1 > tp2 > tp3
        - every value must be finite and positive; otherwise the setup is
          rejected instead of being stored with fabricated numbers
        """
        from opportunity_pool import SetupCandidate, SetupStatus, SetupType

        if not isinstance(selected, dict):
            return None
        try:
            direction = str(selected.get("direction") or "").upper()
            entry_type = str(selected.get("entry_type") or "").upper()
            if direction not in ("LONG", "SHORT"):
                return None
            if entry_type not in ("MARKET", "LIMIT"):
                return None
            entry = float(selected.get("entry"))
            stop = float(selected.get("stop_loss"))
            tp1 = float(selected.get("tp1"))
            tp2 = float(selected.get("tp2"))
            tp3 = float(selected.get("tp3"))
        except (TypeError, ValueError, OverflowError):
            return None
        if not all(math.isfinite(v) and v > 0 for v in (entry, stop, tp1, tp2, tp3)):
            return None
        risk = abs(entry - stop)
        if risk <= 0:
            return None
        if direction == "LONG":
            if not (stop < entry < tp1 < tp2 < tp3):
                return None
        else:
            if not (stop > entry > tp1 > tp2 > tp3):
                return None

        # Reward is measured from the entry, never from the stop.
        rr_tp1 = abs(tp1 - entry) / risk
        rr_tp2 = abs(tp2 - entry) / risk
        rr_tp3 = abs(tp3 - entry) / risk
        if not all(math.isfinite(v) and v > 0 for v in (rr_tp1, rr_tp2, rr_tp3)):
            return None

        strategy_id = str(selected.get("strategy_id") or "unknown")
        strategy_name = str(selected.get("strategy") or strategy_id)

        # Net RR: cost-adjusted value comes from the shared risk engine via the
        # strategy lab. Fall back to the raw partial-exit weighted RR only when
        # the cost-adjusted figure is missing; never invent a number.
        weights = selected.get("partial_exit_weights") or {}
        try:
            w_total = sum(float(weights.get(key, 0.0)) for key in ("tp1", "tp2", "tp3"))
            weighted_rr = (
                (
                    float(weights.get("tp1", 0.0)) * rr_tp1
                    + float(weights.get("tp2", 0.0)) * rr_tp2
                    + float(weights.get("tp3", 0.0)) * rr_tp3
                ) / w_total
                if w_total > 0
                else rr_tp2
            )
        except (TypeError, ValueError, OverflowError):
            weighted_rr = rr_tp2
        try:
            net_rr_after_costs = float(selected.get("estimated_net_rr"))
        except (TypeError, ValueError, OverflowError):
            net_rr_after_costs = None
        if net_rr_after_costs is None or not math.isfinite(net_rr_after_costs):
            net_rr_after_costs = weighted_rr
        net_rr = net_rr_after_costs

        confidence = selected.get("strength")
        try:
            confidence = float(confidence)
        except (TypeError, ValueError, OverflowError):
            confidence = 0.0
        if not math.isfinite(confidence):
            confidence = 0.0

        # Deterministic id: re-scans of an unchanged setup produce the same id,
        # so the pool stays idempotent and dedup can never merge two strategies.
        setup_id = "setup:{}:{}:{}:{:.8g}:{:.8g}:{:.8g}".format(
            symbol, strategy_id, direction, entry, stop, tp1
        )

        reasons = [str(r) for r in (selected.get("reasons") or []) if r]
        candidate = SetupCandidate(
            setup_id=setup_id,
            symbol=symbol,
            strategy_id=strategy_id,
            strategy_name=strategy_name,
            direction=direction,
            entry_type=entry_type,
            entry_price=entry,
            stop_loss=stop,
            tp1=tp1,
            tp2=tp2,
            tp3=tp3,
            rr_tp1=round(rr_tp1, 4),
            rr_tp2=round(rr_tp2, 4),
            rr_tp3=round(rr_tp3, 4),
            net_rr=round(net_rr, 4),
            risk_reward=round(weighted_rr, 4),
            confidence=confidence,
            grade="SELECTED",
            score=confidence,
            net_rr_after_costs=round(net_rr_after_costs, 4),
            status=SetupStatus.DISCOVERED.value,
            setup_type=SetupType.LIMIT.value if entry_type == "LIMIT" else SetupType.MARKET.value,
            regime=str(regime or selected.get("market_regime") or "UNKNOWN"),
            market_phase=str(market_phase or selected.get("market_phase") or "UNKNOWN"),
            reasons=reasons,
            supporting_evidence=[str(v) for v in (selected.get("supporting_event_ids") or [])],
            opposing_evidence=[str(v) for v in (selected.get("opposing_event_ids") or [])],
            created_at_ms=int(time.time() * 1000),
            updated_at_ms=int(time.time() * 1000),
            validated_at_ms=0,  # Set by validate_candidate
            trace_id=trace_id,
        )
        return candidate

    def _accumulate_strategy_telemetry(self, result):
        """Update the strategy generation funnel from the strategy lab report."""
        try:
            lab = result.get("strategy_lab") or {}
            diagnostics = lab.get("diagnostics") or {}
            with self._lock:
                telemetry = self._strategy_telemetry
                telemetry["analyses"] += 1
                telemetry["raw_setups_generated"] += int(diagnostics.get("raw_setup_count") or 0)
                passed = int(diagnostics.get("common_filter_passed_count") or 0)
                telemetry["common_filter_passed"] += passed
                raw = int(diagnostics.get("raw_setup_count") or 0)
                telemetry["common_filter_rejected"] += max(0, raw - passed)
                for row in diagnostics.get("strategies") or []:
                    strategy_id = str(row.get("strategy_id") or "unknown")
                    counts = telemetry["per_strategy"][strategy_id]
                    status = str(row.get("status") or "")
                    if status in ("SELECTED", "FILTERED_NOT_SELECTED", "BLOCKED_COMMON_FILTER"):
                        counts["setups"] += 1
                    else:
                        status_key = {
                            "NO_SETUP": "no_setup",
                            "CONDITION_NOT_MET": "condition_not_met",
                            "MISSING_DATA": "missing_data",
                            "INSUFFICIENT_HISTORY": "insufficient_history",
                            "ERROR": "errors",
                        }.get(status, "other_no_setup")
                        counts[status_key] = counts.get(status_key, 0) + 1
                        reason = str(row.get("reason") or "").strip()
                        if reason:
                            counts.setdefault("reason_counts", defaultdict(int))[reason] += 1
                    if row.get("selected"):
                        counts["selected"] += 1
                        counts["passed"] += 1
                    if status in ("SELECTED", "FILTERED_NOT_SELECTED"):
                        counts["passed"] += 0 if row.get("selected") else 1
                        for reason in row.get("rejection_reasons") or []:
                            telemetry["rejection_reasons"][f"SINGLE_DECISION:{reason}"] += 1
                    elif status == "BLOCKED_COMMON_FILTER":
                        counts["rejected"] += 1
                        for reason in row.get("rejection_reasons") or []:
                            telemetry["rejection_reasons"][str(reason)] += 1
        except Exception as exc:
            self.logger.debug(f"Telemetry accumulation skipped: {exc}")

    def _set_status(self, status):
        with self._lock:
            self._scanner_stats["status"] = status

    def _inc(self, key):
        with self._lock:
            self._scanner_stats[key] = int(self._scanner_stats.get(key, 0)) + 1

    def _log(self, message):
        timestamp = time.strftime("%H:%M:%S", time.localtime())
        self._logs.append(f"{timestamp} {message}")
