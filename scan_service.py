"""Background scan service (requirement F): real scan queue, Telegram-independent.

- The queue, universe inventory and workers live in the runtime service,
  NOT in the Telegram bot: restarting Telegram never resets a scan.
- Every scan command (20/30/50/100/200/500/1000/tümünü tara) enqueues the
  current Gate.io universe into the durable ScanQueue; pending jobs from a
  previous run resume automatically (checkpoint preserved).
- Already-scanned symbols keep their result; no needless re-scan happens
  unless the queue is fully complete and the user explicitly asks again.
- Workers claim atomically, so parallel scans are safe, and the bounded
  analysis gap keeps Gate.io API usage inside rate limits.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("atlas.scan_service")

# Hard ceiling shared by Telegram scan commands and the durable scan queue.
DEFAULT_SCAN_UNIVERSE_LIMIT = 300


class ScanService:
    """Claim-based background scanner over the persistent scan queue."""

    def __init__(
        self,
        runtime,
        queue,
        inventory,
        worker_count: int = 2,
        analysis_gap_seconds: float = 0.5,
    ):
        self.runtime = runtime
        self.queue = queue
        self.inventory = inventory
        self.worker_count = max(1, int(worker_count))
        self.analysis_gap_seconds = max(0.0, float(analysis_gap_seconds))
        self._stop_event = threading.Event()
        self._workers: List[threading.Thread] = []
        self._worker_lock = threading.Lock()
        self._workers_started = False

    # ------------------------------------------------------------------
    # Lifecycle (independent of Telegram)
    # ------------------------------------------------------------------

    def ensure_workers(self) -> bool:
        """Start worker threads if they are not running yet.

        Called at service startup and before each scan command; a pending
        queue from a previous session resumes automatically.
        """
        with self._worker_lock:
            alive = [worker for worker in self._workers if worker.is_alive()]
            if alive:
                # Never clear the shared stop event while a previous worker is
                # still finishing an in-flight analysis. Doing so would revive
                # an orphan and start a second worker set over the same queue.
                self._workers = alive
                self._workers_started = True
                return False
            self._workers = []
            self._workers_started = False
            self._stop_event.clear()
            for index in range(self.worker_count):
                thread = threading.Thread(
                    target=self._worker_loop,
                    daemon=True,
                    name=f"AtlasScanWorker-{index}",
                )
                thread.start()
                self._workers.append(thread)
            self._workers_started = True
            return True

    def stop_scan(self, timeout_seconds: float = 10.0) -> Dict[str, Any]:
        """Signal workers to stop after their current job.

        Claimed jobs keep their lease; an unfinished lease expires and is
        requeued automatically, so stopping never loses work.
        """
        with self._worker_lock:
            # Serialize shutdown against ensure_workers(): otherwise a new
            # start could clear the stop event between set() and join().
            self._stop_event.set()
            workers = list(self._workers)
            for worker in workers:
                worker.join(timeout=timeout_seconds)
            alive_workers = [worker for worker in workers if worker.is_alive()]
            alive = [worker.name for worker in alive_workers]
            # Retain references to workers that did not finish within the
            # timeout. ensure_workers() must see them and must not clear the
            # stop event until they have actually exited.
            self._workers = alive_workers
            self._workers_started = bool(alive_workers)
        return {
            "stopped": not alive,
            "workers_still_alive": alive,
            "progress": self.status(),
        }

    def is_running(self) -> bool:
        with self._worker_lock:
            return any(w.is_alive() for w in self._workers)

    # ------------------------------------------------------------------
    # Scan commands
    # ------------------------------------------------------------------

    def enforce_universe_limit(self) -> Optional[Dict[str, Any]]:
        """Move oversized persisted queues to a new top-300 generation.

        The previous generation remains in SQLite as history; no queue or
        opportunity-pool records are deleted.
        """
        progress = self.queue.progress()
        if int(progress.get("total") or 0) <= DEFAULT_SCAN_UNIVERSE_LIMIT:
            return None
        universe = self.inventory.get_symbols()
        ranker = getattr(self.inventory, "get_ranked_symbols", None)
        if universe and callable(ranker):
            symbols = list(ranker(limit=DEFAULT_SCAN_UNIVERSE_LIMIT) or [])
        else:
            symbols = sorted(universe)[:DEFAULT_SCAN_UNIVERSE_LIMIT]
        if not symbols:
            return None
        result = self.queue.rebuild(
            symbols, batch_tag=f"top_{DEFAULT_SCAN_UNIVERSE_LIMIT}_{int(time.time())}"
        )
        logger.warning(
            "Oversized persisted scan generation replaced by bounded generation | "
            "previous_total=%s new_total=%s ranking=%s",
            progress.get("total"), len(symbols),
            self.inventory.status().get("ranking_source", "alphabetical_fallback"),
        )
        return result

    def start_scan(self, limit: Optional[int] = None) -> Dict[str, Any]:
        """Enqueue the requested scan and make sure workers are running.

        - limit=None scans the top 300 Gate.io contracts by 24h quote turnover.
        - If the current scan generation still has unfinished work, the
          command resumes it instead of restarting — even when the inventory
          is temporarily unavailable.
        - If the current generation is fully complete, a new scan generation
        is opened and the requested number of symbols is queued by 24h quote
        turnover ranking when available, with deterministic alphabetical fallback.
        - A larger request during an unfinished generation extends that same
        generation without resetting completed jobs or checkpoints.
        """
        # "Scan all" means all of the configured liquid universe. Preserve
        # smaller requests and clamp unbounded/larger requests to top 300.
        if limit is None:
            limit = DEFAULT_SCAN_UNIVERSE_LIMIT
        else:
            limit = min(max(0, int(limit)), DEFAULT_SCAN_UNIVERSE_LIMIT)

        progress_before = self.queue.progress()
        has_unfinished = (
            progress_before["pending"] > 0 or progress_before["running"] > 0
        )
        universe = self.inventory.get_symbols()
        ranker = getattr(self.inventory, "get_ranked_symbols", None)
        if universe and callable(ranker):
            ranked_symbols = list(ranker(limit=limit) or [])
        else:
            ranked_symbols = sorted(universe)
            if limit is not None:
                ranked_symbols = ranked_symbols[:max(0, int(limit))]
        if not universe and not has_unfinished:
            return {
                "started": False,
                "reason": "empty_universe",
                "message": "Gate.io evreni boş; envanter yenilenemedi.",
                "progress": progress_before,
            }
        if has_unfinished:
            # Extend the current generation with the requested top-N symbols.
            # enqueue() is idempotent: completed and pending jobs keep their state.
            added = self.queue.enqueue(
                ranked_symbols, batch_tag=f"scan_extend_{int(time.time())}"
            ) if ranked_symbols else 0
            self.ensure_workers()
            progress_after = self.queue.progress()
            inventory_status = self.inventory.status()
            return {
                "started": True,
                "universe_size": len(universe),
                "selected": len(ranked_symbols),
                "selected_preview": ranked_symbols[:5],
                "added": added,
                "resumed": True,
                "ranking_source": inventory_status.get("ranking_source", "alphabetical_fallback"),
                "workers": self.worker_count,
                "scan_generation": self.queue.current_generation(),
                "progress": progress_after,
            }

        queue_result = self.queue.rebuild(
            ranked_symbols, batch_tag=f"scan_{int(time.time())}"
        )
        self.ensure_workers()
        progress_after = self.queue.progress()
        inventory_status = self.inventory.status()
        return {
            "started": True,
            "universe_size": len(universe),
            "selected": len(ranked_symbols),
            "selected_preview": ranked_symbols[:5],
            "added": queue_result["added"],
            "resumed": False,
            "ranking_source": inventory_status.get("ranking_source", "alphabetical_fallback"),
            "workers": self.worker_count,
            "scan_generation": queue_result.get("generation"),
            "progress": progress_after,
        }

    def status(self) -> Dict[str, Any]:
        progress = self.queue.progress()
        progress["workers_running"] = self.is_running()
        progress["inventory"] = self.inventory.status()
        return progress

    # ------------------------------------------------------------------
    # Worker loop
    # ------------------------------------------------------------------

    def _worker_loop(self):
        while not self._stop_event.is_set():
            job = self.queue.claim_next(worker_id=threading.current_thread().name)
            if job is None:
                # Queue drained: idle short sleep then re-check (a parallel
                # command may enqueue more work later).
                if self._stop_event.wait(2.0):
                    break
                progress = self.queue.progress()
                if progress["complete"]:
                    # Nothing left to do; keep the thread alive but cheap so
                    # the next scan command starts instantly.
                    if self._stop_event.wait(5.0):
                        break
                    continue
                continue
            symbol = job["symbol"]
            try:
                outcome = self.runtime.analyze_symbol(
                    symbol, force_refresh=True, track_signal=False, use_websocket=False
                )
                ok = bool(outcome.get("ok"))
                self.queue.complete(symbol, ok=ok, error=None if ok else str(outcome.get("error") or "analysis_failed"))
                if ok:
                    logger.debug(f"Scan {symbol}: ok")
                else:
                    logger.warning(
                        f"Scan {symbol} failed: {str(outcome.get('error'))[:180]}"
                    )
            except Exception as exc:
                logger.error(f"Scan worker error on {symbol}: {exc}")
                self.queue.complete(symbol, ok=False, error=str(exc)[:180])
            # Bounded gap between analyses keeps Gate.io usage rate-limit safe.
            if self._stop_event.wait(self.analysis_gap_seconds):
                break
