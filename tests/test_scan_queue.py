"""Offline tests for the persistent scan queue: claim atomicity, retries,
crash recovery via lease expiry, rebuild without reset, parallel safety."""
import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scan_queue import ScanQueue, DONE, FAILED, PENDING, RUNNING


def make_queue(tmp_path, **kwargs):
    defaults = {"base_path": str(tmp_path / "q"), "lease_seconds": 300, "max_retries": 3}
    defaults.update(kwargs)
    return ScanQueue(**defaults)


def test_enqueue_and_claim_order(tmp_path):
    queue = make_queue(tmp_path)
    assert queue.enqueue(["BTC/USDT:USDT", "ETH/USDT:USDT"]) == 2
    first = queue.claim_next("w1")
    assert first["symbol"] == "BTC/USDT:USDT"
    progress = queue.progress()
    assert progress["running"] == 1
    assert progress["pending"] == 1


def test_enqueue_is_idempotent(tmp_path):
    queue = make_queue(tmp_path)
    assert queue.enqueue(["BTC/USDT:USDT"]) == 1
    assert queue.enqueue(["BTC/USDT:USDT"]) == 0
    assert queue.progress()["total"] == 1


def test_complete_done_and_failed(tmp_path):
    queue = make_queue(tmp_path, max_retries=2)
    queue.enqueue(["A/USDT:USDT", "B/USDT:USDT"])
    job = queue.claim_next("w1")
    assert queue.complete(job["symbol"], ok=True) is True
    assert queue.progress()["done"] == 1

    job_b = queue.claim_next("w1")
    assert queue.complete(job_b["symbol"], ok=False, error="timeout") is True
    progress = queue.progress()
    assert progress["pending"] == 1  # requeued for retry
    assert progress["failed"] == 0
    job_retry = queue.claim_next("w1")
    assert job_retry["symbol"] == "B/USDT:USDT"
    assert job_retry["retries"] == 1


def test_failed_after_retry_limit(tmp_path):
    queue = make_queue(tmp_path, max_retries=1)
    queue.enqueue(["A/USDT:USDT"])
    job = queue.claim_next("w1")
    queue.complete(job["symbol"], ok=False, error="err1")
    job2 = queue.claim_next("w1")
    queue.complete(job2["symbol"], ok=False, error="err2")
    progress = queue.progress()
    assert progress["failed"] == 1
    failed = queue.failed_symbols()
    assert failed[0]["symbol"] == "A/USDT:USDT"
    assert failed[0]["error"] == "err2"


def test_requeue_failed_manually(tmp_path):
    queue = make_queue(tmp_path, max_retries=1)
    queue.enqueue(["A/USDT:USDT"])
    job = queue.claim_next("w1")
    queue.complete(job["symbol"], ok=False, error="err1")
    job2 = queue.claim_next("w1")
    queue.complete(job2["symbol"], ok=False, error="err2")
    assert queue.requeue_failed() == 1
    assert queue.progress()["pending"] == 1


def test_complete_only_claimed_jobs(tmp_path):
    queue = make_queue(tmp_path)
    queue.enqueue(["A/USDT:USDT"])
    # Not claimed: cannot be completed
    assert queue.complete("A/USDT:USDT", ok=True) is False
    # Unknown symbol
    assert queue.complete("NOPE/USDT:USDT", ok=True) is False


def test_claim_atomic_parallel_workers(tmp_path):
    queue = make_queue(tmp_path)
    symbols = [f"S{i}/USDT:USDT" for i in range(50)]
    queue.enqueue(symbols)
    claimed = []
    lock = threading.Lock()

    def worker(worker_id):
        while True:
            job = queue.claim_next(f"w{worker_id}")
            if job is None:
                break
            with lock:
                claimed.append(job["symbol"])
            queue.complete(job["symbol"], ok=True)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert len(claimed) == 50
    assert len(set(claimed)) == 50, "two workers claimed the same symbol"
    progress = queue.progress()
    assert progress["done"] == 50
    assert progress["complete"] is True


def test_lease_expiry_recovers_crashed_worker(tmp_path):
    queue = make_queue(tmp_path, lease_seconds=30)
    # Simulate a short lease directly (constructor clamps to >= 30s)
    queue.lease_seconds = 1
    queue.enqueue(["A/USDT:USDT"])
    job = queue.claim_next("w1")
    assert queue.progress()["running"] == 1
    # Simulate worker crash: lease expires after ~1s
    import time as time_mod
    time_mod.sleep(1.2)
    recovered = queue.claim_next("w2")
    assert recovered is not None
    assert recovered["symbol"] == "A/USDT:USDT"


def test_rebuild_keeps_existing_state(tmp_path):
    queue = make_queue(tmp_path)
    queue.enqueue(["A/USDT:USDT", "B/USDT:USDT"])
    job = queue.claim_next("w1")
    queue.complete(job["symbol"], ok=True)
    # Universe changed: a new symbol appears
    result = queue.rebuild(["A/USDT:USDT", "B/USDT:USDT", "C/USDT:USDT"])
    assert result["added"] == 1
    progress = queue.progress()
    assert progress["done"] == 1  # completed work preserved
    assert progress["total"] == 3
    assert progress["next_symbol"] in ("B/USDT:USDT", "C/USDT:USDT")


def test_state_survives_restart(tmp_path):
    queue = make_queue(tmp_path)
    queue.enqueue(["A/USDT:USDT", "B/USDT:USDT"])
    job = queue.claim_next("w1")
    queue.complete(job["symbol"], ok=True)
    queue.close()

    restored = ScanQueue(base_path=str(tmp_path / "q"))
    progress = restored.progress()
    assert progress["done"] == 1
    assert progress["pending"] == 1
    restored.close()


def test_malformed_symbols_ignored(tmp_path):
    queue = make_queue(tmp_path)
    assert queue.enqueue(["", None, "  ", "BTC/USDT:USDT"]) == 1
    assert queue.progress()["total"] == 1
