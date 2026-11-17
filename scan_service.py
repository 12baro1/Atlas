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
            if self._workers_started and any(w.is_alive() for w in self._workers):
                return False
            self._stop_event.clear()
            self._workers = []
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
        self._stop_event.set()
        for worker in list(self._workers):
            worker.join(timeout=timeout_seconds)
        with self._worker_lock:
            alive = [w.name for w in self._workers if w.is_alive()]
            self._workers = []
            self._workers_started = False
        return {"stopped": True, "workers_still_alive": alive, "progress": self.status()}

    def is_running(self) -> bool:
        with self._worker_lock:
            return any(w.is_alive() for w in self._workers)

    # ------------------------------------------------------------------
    # Scan commands
    # ------------------------------------------------------------------

    def start_scan(self, limit: Optional[int] = None) -> Dict[str, Any]:
        """Enqueue the requested scan and make sure workers are running.

        - limit=None scans the whole current Gate.io universe.
        - If the queue still has unfinished work, the command resumes it
          instead of restarting from scratch — even when the inventory is
          temporarily unavailable.
        - If the queue is fully complete, the requested number of completed
          symbols is requeued for an explicit user-driven re-scan (the
          service never auto-resets results on its own).
        """
        progress_before = self.queue.progress()
        has_unfinished = (
            progress_before["pending"] > 0 or progress_before["running"] > 0
        )
        universe = self.inventory.get_symbols()
        if not universe and not has_unfinished:
            return {
                "started": False,
                "reason": "empty_universe",
                "message": "Gate.io evreni boş; envanter yenilenemedi.",
                "progress": progress_before,
            }
        if universe and (limit is None or int(limit) >= len(universe)):
            selected = universe
        elif universe:
            selected = sorted(universe)[: int(limit)]
        else:
            selected = []  # resume-only: nothing new to enqueue

        queue_result = self.queue.rebuild(selected, batch_tag=f"scan_{int(time.time())}")
        self.ensure_workers()
        progress_after = self.queue.progress()
        return {
            "started": True,
            "universe_size": len(universe),
            "selected": len(selected),
            "added": queue_result["added"],
            "resumed": progress_before["pending"] > 0 or progress_before["running"] > 0,
            "workers": self.worker_count,
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
                    symbol, force_refresh=True, track_signal=False
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
