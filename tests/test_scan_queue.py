"""Offline tests for the persistent scan queue: claim atomicity, retries,
crash recovery via lease expiry, rebuild without reset, parallel safety."""
import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scan_queue import ScanQueue, DONE, FAILED, PENDING, RUNNING


def test_requeue_completed_reopens_only_done_and_failed_jobs(tmp_path):
    queue = make_queue(tmp_path, max_retries=1)
    queue.start_new_period("revalidate")
    queue.enqueue(["DONE/USDT", "FAILED/USDT", "PENDING/USDT", "RUNNING/USDT"])
    assert queue.claim_next()["symbol"] == "DONE/USDT"
    queue.complete("DONE/USDT", ok=True)
    # Put one row directly in FAILED state; complete(ok=False) is retryable
    # by design and may be claimed again before reaching its retry limit.
    queue._thread_conn().execute(
        "UPDATE scan_jobs SET state = ? WHERE symbol = ? AND scan_generation = ?",
        (FAILED, "FAILED/USDT", queue.current_generation()),
    )
    assert queue.claim_next()["symbol"] == "PENDING/USDT"

    count = queue.requeue_completed([
        "DONE/USDT", "FAILED/USDT", "PENDING/USDT", "MISSING/USDT"
    ], batch_tag="setup_revalidation")

    assert count == 2
    states = {
        row[0]: row[1]
        for row in queue._thread_conn().execute(
            "SELECT symbol, state FROM scan_jobs WHERE scan_generation = ?",
            (queue.current_generation(),),
        ).fetchall()
    }
    assert states["DONE/USDT"] == PENDING
    assert states["FAILED/USDT"] == PENDING
    assert states["PENDING/USDT"] == RUNNING
    queue.close()

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


def test_rebuild_opens_new_generation_and_requeues_all(tmp_path):
    """rebuild opens a new scan generation so completed scans never block
    a new period; older generations keep their history."""
    queue = make_queue(tmp_path)
    queue.enqueue(["A/USDT:USDT", "B/USDT:USDT"])
    job = queue.claim_next("w1")
    queue.complete(job["symbol"], ok=True)
    old_progress = queue.progress(generation=0)
    assert old_progress["done"] == 1  # gen 0: A done, B pending

    # Universe changed: a new symbol appears. rebuild opens gen 1.
    result = queue.rebuild(["A/USDT:USDT", "B/USDT:USDT", "C/USDT:USDT"])
    assert result["generation"] == 1
    assert result["added"] == 3  # all symbols are new in gen 1
    progress = queue.progress(generation=1)
    assert progress["total"] == 3
    assert progress["pending"] == 3
    assert progress["done"] == 0  # gen 1 starts fresh
    assert progress["next_symbol"] in ("A/USDT:USDT", "B/USDT:USDT", "C/USDT:USDT")
    # Old generation history is preserved
    assert queue.progress(generation=0)["done"] == 1


def test_rebuild_resumes_unfinished_without_new_generation(tmp_path):
    """When the current generation has unfinished work, start_scan resumes
    instead of opening a new generation (covered in scan_service tests, but
    the queue level keeps jobs intact)."""
    queue = make_queue(tmp_path)
    queue.enqueue(["A/USDT:USDT", "B/USDT:USDT"])
    job = queue.claim_next("w1")
    # A is running, B is pending - no new period should be forced by enqueue.
    added = queue.enqueue(["A/USDT:USDT", "B/USDT:USDT"])
    assert added == 0  # same generation, already known: no-op
    progress = queue.progress()
    assert progress["running"] == 1
    assert progress["pending"] == 1


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


def test_ranked_generation_metadata_and_pending_reorder_survive_restart(tmp_path):
    queue = make_queue(tmp_path)
    queue.enqueue(["AAA/USDT:USDT", "BBB/USDT:USDT", "CCC/USDT:USDT"])
    first = queue.claim_next("w1")
    assert first["symbol"] == "AAA/USDT:USDT"
    queue.complete(first["symbol"], ok=True)

    ranked = ["CCC/USDT:USDT", "BBB/USDT:USDT", "AAA/USDT:USDT"]
    queue.reorder_pending(ranked)
    queue.set_generation_ranking(ranked, "gateio_24h_quote_volume")
    assert queue.claim_next("w1")["symbol"] == "CCC/USDT:USDT"
    assert queue.progress()["done"] == 1
    queue.close()

    restored = ScanQueue(base_path=str(tmp_path / "q"))
    metadata = restored.generation_ranking()
    assert metadata["symbols"] == ranked
    assert metadata["ranking_source"] == "gateio_24h_quote_volume"
    assert restored.progress()["done"] == 1
    restored.close()


def test_malformed_symbols_ignored(tmp_path):
    queue = make_queue(tmp_path)
    assert queue.enqueue(["", None, "  ", "BTC/USDT:USDT"]) == 1
    assert queue.progress()["total"] == 1
