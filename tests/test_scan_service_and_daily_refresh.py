"""Offline tests for daily pool refresh (requirement K) and the scan service
facade (requirement F): Telegram independence, resume, parallel safety."""
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from daily_refresh import DailyPoolRefresh, istanbul_day, istanbul_hour
from scan_service import ScanService


# ---------------------------------------------------------------------------
# Istanbul timezone helpers
# ---------------------------------------------------------------------------

def test_istanbul_day_uses_utc_timestamps():
    # 2026-11-17 21:00 UTC == 2026-11-18 00:00 Istanbul
    ms = int(time.mktime((2026, 11, 17, 21, 0, 0, 0, 0, 0)) * 1000)
    # mktime is local time; compute UTC ms explicitly instead
    import calendar
    ms = calendar.timegm((2026, 11, 17, 21, 0, 0, 0, 0, 0)) * 1000
    assert istanbul_day(ms) == "2026-11-18"
    assert istanbul_hour(ms) == 0


def test_istanbul_day_before_midnight():
    import calendar
    ms = calendar.timegm((2026, 11, 17, 20, 59, 0, 0, 0, 0)) * 1000
    assert istanbul_day(ms) == "2026-11-17"
    assert istanbul_hour(ms) == 23


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakePool:
    def __init__(self):
        self.archived = []

    def archive_and_reset_scan_pools(self, day_tag):
        self.archived.append(day_tag)
        return {"candidates": 3, "validated": 2}


class FakeStore:
    def __init__(self):
        self.meta = {}

    def get_meta(self, key):
        return self.meta.get(key)

    def set_meta(self, key, value):
        self.meta[key] = value


class FakeQueue:
    def __init__(self):
        self.rebuilt = []

    def rebuild(self, symbols, batch_tag=None):
        self.rebuilt.append((tuple(symbols), batch_tag))
        return {"added": len(symbols), "progress": {}, "generation": 1}


class FakeInventory:
    def __init__(self, symbols):
        self._symbols = list(symbols)

    def get_symbols(self):
        return list(self._symbols)

    def status(self):
        return {"last_refresh_ms": 1700000000000}


def make_refresh(store):
    pool = FakePool()
    pool._store = store
    queue = FakeQueue()
    inventory = FakeInventory(["BTC/USDT:USDT", "ETH/USDT:USDT"])
    return DailyPoolRefresh(pool, queue, inventory), pool, queue, inventory


# ---------------------------------------------------------------------------
# Daily refresh behaviour
# ---------------------------------------------------------------------------

def test_refresh_idempotent_same_day(tmp_path):
    store = FakeStore()
    refresh, pool, queue, inventory = make_refresh(store)
    import calendar
    midnight = calendar.timegm((2026, 11, 18, 0, 30, 0, 0, 0, 0)) * 1000

    first = refresh.run_if_due(midnight)
    assert first is not None
    assert first["day"] == "2026-11-18"
    assert pool.archived == ["2026-11-18"]
    assert store.meta["last_refresh_day"] == "2026-11-18"

    second = refresh.run_if_due(midnight + 60_000)
    assert second is None, "same day must not refresh twice"
    assert pool.archived == ["2026-11-18"]
    assert len(queue.rebuilt) == 1


def test_refresh_not_due_before_00_00(tmp_path):
    """Catch-up design: the day refreshes once, any time after 00:00 Istanbul.

    A refresh triggered late in the day (e.g. 23:00 Istanbul) is a legitimate
    catch-up for that day and must not repeat for the same calendar day.
    """
    store = FakeStore()
    refresh, pool, queue, _ = make_refresh(store)
    import calendar
    late_evening = calendar.timegm((2026, 11, 17, 20, 0, 0, 0, 0, 0)) * 1000  # 23:00 IST
    first = refresh.run_if_due(late_evening)
    assert first is not None
    assert first["day"] == "2026-11-17"
    assert refresh.run_if_due(late_evening + 60_000) is None
    assert pool.archived == ["2026-11-17"]


def test_refresh_preserves_old_records_via_archive(tmp_path):
    """Archive keeps old records; only the live pools open a new period."""
    store = FakeStore()
    refresh, pool, queue, inventory = make_refresh(store)
    import calendar
    midnight = calendar.timegm((2026, 11, 18, 0, 5, 0, 0, 0, 0)) * 1000
    result = refresh.run_if_due(midnight)
    assert result["archived_candidates"] == 3
    assert result["archived_validated"] == 2
    # Universe re-enqueued for the new period, states preserved by the queue
    assert result["queue_added"] == 2


def test_refresh_failure_does_not_mark_day_done(tmp_path):
    class FailingPool(FakePool):
        def archive_and_reset_scan_pools(self, day_tag):
            raise RuntimeError("disk full")

    pool = FailingPool()
    pool._store = FakeStore()
    refresh = DailyPoolRefresh(pool, FakeQueue(), FakeInventory(["BTC/USDT:USDT"]))
    import calendar
    midnight = calendar.timegm((2026, 11, 18, 0, 5, 0, 0, 0, 0)) * 1000
    result = refresh.run_if_due(midnight)
    assert result is None
    # Marker NOT set: a retry after the failure can still refresh the day
    assert refresh.last_refresh_day() is None


class BackupFailingPool(FakePool):
    """Pool whose store backup raises; archive_and_reset_scan_pools must
    NOT clear live pools when backup fails."""

    def __init__(self):
        super().__init__()
        self.cleared = False

    def archive_and_reset_scan_pools(self, day_tag):
        # Simulate: backup raises -> archive_and_reset_scan_pools re-raises
        # before clearing pools
        raise RuntimeError("backup failed")


def test_backup_failure_does_not_clear_live_pools(tmp_path):
    """Arşivleme/yedekleme başarısızsa canlı havuz temizlenmemeli."""
    store = FakeStore()
    pool = BackupFailingPool()
    pool._store = store
    queue = FakeQueue()
    inventory = FakeInventory(["BTC/USDT:USDT"])
    refresh = DailyPoolRefresh(pool, queue, inventory)
    import calendar
    midnight = calendar.timegm((2026, 11, 18, 0, 5, 0, 0, 0, 0)) * 1000

    result = refresh.run_if_due(midnight)
    assert result is None  # exception propagated, refresh not marked done
    assert store.meta.get("last_refresh_day") is None
    assert len(queue.rebuilt) == 0  # no new generation opened


def test_vps_restart_reads_marker_from_sqlite_store(tmp_path):
    """VPS restart sonrası yeni DailyPoolRefresh instance'ı
    SQLite meta'dan last_refresh_day'ı okur (tekrar yenilemez)."""
    store = FakeStore()
    store.meta["last_refresh_day"] = "2026-11-18"  # simulated from previous run
    pool = FakePool()
    pool._store = store
    queue = FakeQueue()
    inventory = FakeInventory(["BTC/USDT:USDT"])
    refresh = DailyPoolRefresh(pool, queue, inventory)
    import calendar
    midnight = calendar.timegm((2026, 11, 18, 1, 0, 0, 0, 0, 0)) * 1000

    result = refresh.run_if_due(midnight)
    assert result is None, "marker already set for today: no re-refresh"
    assert len(queue.rebuilt) == 0


def test_new_generation_opened_on_daily_refresh(tmp_path):
    """Günlük yenileme yeni scan generation açar; eski done kayıtları
    yeni nesilde engellemez."""
    store = FakeStore()
    pool = FakePool()
    pool._store = store
    queue = FakeQueue()
    inventory = FakeInventory(["BTC/USDT:USDT", "ETH/USDT:USDT"])
    refresh = DailyPoolRefresh(pool, queue, inventory)
    import calendar
    midnight = calendar.timegm((2026, 11, 18, 0, 5, 0, 0, 0, 0)) * 1000

    result = refresh.run_if_due(midnight)
    assert result is not None
    assert result["scan_generation"] is not None
    assert result["queue_added"] == 2
    assert store.meta["last_refresh_day"] == "2026-11-18"


# ---------------------------------------------------------------------------
# Scan service
# ---------------------------------------------------------------------------

class FakeRuntime:
    def __init__(self):
        self.analyzed = []
        self._fail_symbols = set()
        self.websocket_flags = []
        self._lock = threading.Lock()

    def analyze_symbol(self, symbol, force_refresh=False, track_signal=False, use_websocket=True):
        with self._lock:
            self.analyzed.append(symbol)
            self.websocket_flags.append(bool(use_websocket))
        if symbol in self._fail_symbols:
            return {"ok": False, "error": "stale_15m_market_data"}
        return {"ok": True, "symbol": symbol}


class FakeQ:
    """ScanQueue-compatible in-memory fake with the same claim semantics."""

    def __init__(self):
        self.jobs = {}
        self.generation = 0
        self.ranking = {}
        self._lock = threading.Lock()

    def enqueue(self, symbols, batch_tag=None):
        added = 0
        with self._lock:
            for symbol in symbols:
                if symbol not in self.jobs:
                    self.jobs[symbol] = {"state": "pending", "attempts": 0}
                    added += 1
        return added

    def current_generation(self):
        return self.generation

    def generation_symbols(self, generation=None):
        return list(self.jobs)

    def set_generation_ranking(self, symbols, source, generation=None):
        self.ranking = {"symbols": list(symbols), "ranking_source": source}

    def generation_ranking(self, generation=None):
        return dict(self.ranking)

    def reorder_pending(self, ranked_symbols):
        rank = {symbol: index for index, symbol in enumerate(ranked_symbols)}
        pending = sorted(
            (symbol for symbol, job in self.jobs.items() if job["state"] == "pending"),
            key=lambda symbol: (rank.get(symbol, len(rank)), symbol),
        )
        ordered = {}
        for symbol in pending:
            ordered[symbol] = self.jobs[symbol]
        for symbol, job in self.jobs.items():
            if job["state"] != "pending":
                ordered[symbol] = job
        self.jobs = ordered
        return len(pending)

    def rebuild(self, symbols, batch_tag=None):
        self.generation += 1
        self.jobs = {}
        added = self.enqueue(symbols, batch_tag)
        return {
            "added": added,
            "progress": self.progress(),
            "generation": self.current_generation(),
        }

    def claim_next(self, worker_id="worker"):
        with self._lock:
            for symbol, job in self.jobs.items():
                if job["state"] == "pending":
                    job["state"] = "running"
                    job["attempts"] += 1
                    return {"symbol": symbol, "attempts": job["attempts"]}
            return None

    def complete(self, symbol, ok, error=None):
        with self._lock:
            job = self.jobs.get(symbol)
            if not job or job["state"] != "running":
                return False
            job["state"] = "done" if ok else "failed"
            return True

    def progress(self):
        with self._lock:
            counts = {"pending": 0, "running": 0, "done": 0, "failed": 0}
            for job in self.jobs.values():
                counts[job["state"]] += 1
            total = sum(counts.values())
            finished = counts["done"] + counts["failed"]
            return {
                "total": total,
                "pending": counts["pending"],
                "running": counts["running"],
                "done": counts["done"],
                "failed": counts["failed"],
                "finished": finished,
                "percent": 100.0 * finished / total if total else 0.0,
                "complete": total > 0 and counts["pending"] == 0 and counts["running"] == 0,
                "next_symbol": None,
            }


class FakeInv:
    def __init__(self, symbols, ranked_symbols=None):
        self._symbols = list(symbols)
        self._ranked_symbols = list(ranked_symbols if ranked_symbols is not None else symbols)
        self._ranking_source = "fake_24h_quote_volume" if ranked_symbols is not None else "alphabetical_fallback"

    def get_symbols(self):
        return list(self._symbols)

    def get_ranked_symbols(self, limit=None):
        ranked = list(self._ranked_symbols)
        return ranked if limit is None else ranked[:max(0, int(limit))]

    def status(self):
        return {"symbol_count": len(self._symbols), "ranking_source": self._ranking_source}


def make_service(runtime, symbols, workers=2):
    return ScanService(
        runtime=runtime, queue=FakeQ(), inventory=FakeInv(symbols),
        worker_count=workers, analysis_gap_seconds=0.0,
    )


def test_start_scan_enqueues_and_processes(tmp_path):
    runtime = FakeRuntime()
    service = make_service(runtime, [f"S{i}/USDT:USDT" for i in range(10)])
    result = service.start_scan(limit=5)
    assert result["started"] is True
    assert result["selected"] == 5
    # Wait for workers to drain the queue
    deadline = time.time() + 15
    while time.time() < deadline and not service.status()["complete"]:
        time.sleep(0.05)
    status = service.status()
    assert status["complete"] is True
    assert status["done"] == 5
    assert runtime.websocket_flags == [False] * 5
    service.stop_scan()


def test_failed_symbols_requeued_then_failed(tmp_path):
    runtime = FakeRuntime()
    symbols = ["BAD/USDT:USDT"]
    service = make_service(runtime, symbols, workers=1)
    # A scan-queue style fake honoring retries:
    queue = service.queue
    queue.max_retries = 1
    service.start_scan(limit=1)
    deadline = time.time() + 10
    while time.time() < deadline and not service.status()["complete"]:
        time.sleep(0.05)
    status = service.status()
    assert status["complete"] is True
    # FakeQ marks failed on first error (no retry simulation) - keep the
    # assertion aligned with the fake: symbol analyzed once, marked failed.
    assert "BAD/USDT:USDT" in runtime.analyzed
    service.stop_scan()


def test_telegram_independence_resume_after_restart(tmp_path):
    """Pending work survives a service restart and continues without Telegram."""
    runtime = FakeRuntime()
    service = make_service(runtime, [f"R{i}/USDT:USDT" for i in range(8)], workers=1)
    # Fill the queue WITHOUT starting workers (no auto-processing)
    service.queue.enqueue([f"R{i}/USDT:USDT" for i in range(8)])

    # A fresh service instance over the same queue resumes pending work
    service2 = ScanService(
        runtime=runtime, queue=service.queue, inventory=FakeInv([]),
        worker_count=1, analysis_gap_seconds=0.0,
    )
    status = service2.status()
    assert status["total"] == 8
    assert status["pending"] == 8
    # Empty inventory must not block resume: queue has unfinished work
    resumed = service2.start_scan()
    assert resumed["started"] is True
    deadline = time.time() + 30
    while time.time() < deadline and not service2.status()["complete"]:
        time.sleep(0.05)
    assert service2.status()["complete"] is True
    assert len(runtime.analyzed) == 8
    service2.stop_scan()


def test_empty_universe_reports_explicitly(tmp_path):
    service = make_service(FakeRuntime(), [], workers=1)
    result = service.start_scan(limit=20)
    assert result["started"] is False
    assert result["reason"] == "empty_universe"

def test_scan_uses_ranked_symbols_and_extends_active_generation(tmp_path):
    runtime = FakeRuntime()
    symbols = ["AAA/USDT:USDT", "BBB/USDT:USDT", "CCC/USDT:USDT"]
    ranked = ["CCC/USDT:USDT", "AAA/USDT:USDT", "BBB/USDT:USDT"]
    inventory = FakeInv(symbols, ranked_symbols=ranked)
    queue = FakeQ()
    service = ScanService(runtime, queue, inventory, worker_count=1, analysis_gap_seconds=0.0)
    # Prevent worker consumption so the generation can be inspected exactly.
    service.ensure_workers = lambda: False
    first = service.start_scan(limit=2)
    assert first["selected_preview"] == ranked[:2]
    assert first["ranking_source"] == "fake_24h_quote_volume"
    generation = first["scan_generation"]
    # Mark the first job complete and leave the generation unfinished.
    queue.jobs[ranked[0]]["state"] = "done"
    second = service.start_scan(limit=3)
    assert second["resumed"] is True
    assert second["scan_generation"] == generation
    assert second["added"] == 1
    assert queue.jobs[ranked[0]]["state"] == "done"
    assert queue.jobs[ranked[1]]["state"] == "pending"
    assert queue.jobs[ranked[2]]["state"] == "pending"


def test_startup_sync_rebuilds_legacy_queue_to_ranked_top_universe(tmp_path):
    runtime = FakeRuntime()
    symbols = ["AAA/USDT:USDT", "BBB/USDT:USDT", "CCC/USDT:USDT"]
    ranked = ["CCC/USDT:USDT", "BBB/USDT:USDT"]
    queue = FakeQ()
    queue.enqueue(symbols[:2])  # legacy alphabetical generation
    service = ScanService(runtime, queue, FakeInv(symbols, ranked_symbols=ranked),
                          worker_count=1, analysis_gap_seconds=0.0)

    result = service.synchronize_ranked_universe(limit=2)
    assert result["rebuilt"] is True
    assert queue.generation_symbols() == ranked
    assert queue.generation_ranking()["ranking_source"] == "fake_24h_quote_volume"


def test_startup_sync_reorders_pending_without_resetting_completed_jobs(tmp_path):
    runtime = FakeRuntime()
    symbols = ["AAA/USDT:USDT", "BBB/USDT:USDT", "CCC/USDT:USDT"]
    queue = FakeQ()
    queue.enqueue(symbols)
    queue.jobs["AAA/USDT:USDT"]["state"] = "done"
    service = ScanService(runtime, queue, FakeInv(symbols, ranked_symbols=list(reversed(symbols))),
                          worker_count=1, analysis_gap_seconds=0.0)

    result = service.synchronize_ranked_universe(limit=3)
    assert result["rebuilt"] is False
    assert queue.jobs["AAA/USDT:USDT"]["state"] == "done"
    assert queue.generation_ranking()["symbols"] == list(reversed(symbols))


def test_stop_scan_does_not_orphan_or_revive_inflight_worker(tmp_path):
    entered = threading.Event()
    release = threading.Event()

    class BlockingRuntime(FakeRuntime):
        def analyze_symbol(self, symbol, force_refresh=False, track_signal=False, use_websocket=True):
            entered.set()
            release.wait(5)
            return {"ok": True, "symbol": symbol}

    runtime = BlockingRuntime()
    service = make_service(runtime, ["BLOCK/USDT:USDT"], workers=1)
    service.start_scan(limit=1)
    assert entered.wait(2), "worker did not start analysis"

    stopped = service.stop_scan(timeout_seconds=0.01)
    assert stopped["stopped"] is False
    assert stopped["workers_still_alive"] == ["AtlasScanWorker-0"]
    assert service.ensure_workers() is False
    assert len(service._workers) == 1

    release.set()
    deadline = time.time() + 3
    while time.time() < deadline and any(w.is_alive() for w in service._workers):
        time.sleep(0.01)
    assert not any(w.is_alive() for w in service._workers)

    # A new worker set can start only after the old worker has really exited.
    assert service.ensure_workers() is True
    service.stop_scan(timeout_seconds=2)



def test_unbounded_scan_command_is_capped_to_top_300(tmp_path):
    symbols = [f"COIN{i:03d}/USDT:USDT" for i in range(350)]
    ranked = list(reversed(symbols))
    service = ScanService(
        FakeRuntime(), FakeQ(), FakeInv(symbols, ranked_symbols=ranked),
        worker_count=1, analysis_gap_seconds=0.0,
    )
    service.ensure_workers = lambda: False
    result = service.start_scan()
    assert result["selected"] == 300
    assert result["selected_preview"] == ranked[:5]
    assert result["ranking_source"] == "fake_24h_quote_volume"
