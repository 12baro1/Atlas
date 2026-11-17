"""SQLite scan_queue migration tests (requirement: critical migration).

Tests the migration from the OLD schema where scan_jobs.symbol was the
single-column PRIMARY KEY to the NEW composite PRIMARY KEY (symbol,
scan_generation). All tests are offline and deterministic.
"""
import os
import sys
import sqlite3
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from scan_queue import ScanQueue, PENDING, DONE, FAILED, RUNNING


# ---------------------------------------------------------------------------
# Helpers: build an OLD-schema database
# ---------------------------------------------------------------------------

def _make_old_schema_db(db_path: str) -> None:
    """Create a scan_queue.db with the OLD single-column-PK schema."""
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript("""
            CREATE TABLE scan_jobs (
                symbol TEXT PRIMARY KEY,
                state TEXT NOT NULL CHECK (state IN ('pending','running','done','failed')),
                enqueued_at_ms INTEGER NOT NULL,
                claimed_at_ms INTEGER,
                lease_until_ms INTEGER,
                attempts INTEGER NOT NULL DEFAULT 0,
                retries INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                completed_at_ms INTEGER,
                batch_tag TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_scan_jobs_state
                ON scan_jobs(state, enqueued_at_ms);
        """)
        now_ms = int(time.time() * 1000)
        conn.executemany(
            """
            INSERT INTO scan_jobs(
                symbol, state, enqueued_at_ms, claimed_at_ms, lease_until_ms,
                attempts, retries, last_error, completed_at_ms, batch_tag
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("BTC/USDT:USDT", DONE, now_ms - 1000, now_ms - 900,
                 now_ms - 800, 1, 0, None, now_ms - 800, "batch-1"),
                ("ETH/USDT:USDT", PENDING, now_ms - 1000, None, None, 0, 0,
                 None, None, "batch-1"),
                ("SOL/USDT:USDT", FAILED, now_ms - 1000, now_ms - 900,
                 None, 2, 2, "rate_limit", None, "batch-1"),
            ],
        )
        conn.commit()
    finally:
        conn.close()


def _make_old_schema_db_with_sidecars(tmp_path) -> str:
    """Create old-schema db with WAL/SHM sidecar files present."""
    db_path = str(tmp_path / "scan_queue.db")
    _make_old_schema_db(db_path)
    # Simulate leftover WAL/SHM from a previous run
    for suffix in ("-wal", "-shm"):
        p = db_path + suffix
        if not os.path.exists(p):
            with open(p, "wb") as f:
                f.write(b"\x00" * 16)
    return db_path


# ---------------------------------------------------------------------------
# Migration: old database opens successfully
# ---------------------------------------------------------------------------

def test_old_schema_migrates_to_composite_pk(tmp_path):
    """Opening an old-schema database migrates it to (symbol, scan_generation) PK."""
    db_path = str(tmp_path / "scan_queue.db")
    _make_old_schema_db(db_path)

    queue = ScanQueue(base_path=str(tmp_path))

    # Schema now has composite PK
    conn = queue._thread_conn()
    pk_cols = [
        row[1] for row in conn.execute("PRAGMA table_info(scan_jobs)")
        if row[5] > 0
    ]
    assert pk_cols == ["symbol", "scan_generation"], pk_cols

    # All old records preserved with scan_generation=0
    rows = conn.execute(
        "SELECT symbol, state, scan_generation FROM scan_jobs ORDER BY symbol"
    ).fetchall()
    assert len(rows) == 3
    assert ("BTC/USDT:USDT", DONE, 0) in rows
    assert ("ETH/USDT:USDT", PENDING, 0) in rows
    assert ("SOL/USDT:USDT", FAILED, 0) in rows
    queue.close()


def test_old_schema_with_wal_sidecars_migrates(tmp_path):
    """Old schema with WAL/SHM sidecars migrates cleanly."""
    db_path = _make_old_schema_db_with_sidecars(tmp_path)
    queue = ScanQueue(base_path=str(tmp_path))
    conn = queue._thread_conn()
    count = conn.execute("SELECT COUNT(*) FROM scan_jobs").fetchone()[0]
    assert count == 3
    pk_cols = [
        row[1] for row in conn.execute("PRAGMA table_info(scan_jobs)")
        if row[5] > 0
    ]
    assert pk_cols == ["symbol", "scan_generation"]
    queue.close()


def test_migration_is_idempotent_reopen(tmp_path):
    """Reopening an already-migrated database does not duplicate or lose data."""
    db_path = str(tmp_path / "scan_queue.db")
    _make_old_schema_db(db_path)

    queue1 = ScanQueue(base_path=str(tmp_path))
    count1 = queue1._thread_conn().execute("SELECT COUNT(*) FROM scan_jobs").fetchone()[0]
    queue1.close()

    queue2 = ScanQueue(base_path=str(tmp_path))
    count2 = queue2._thread_conn().execute("SELECT COUNT(*) FROM scan_jobs").fetchone()[0]
    assert count1 == count2 == 3
    queue2.close()


def test_migration_integrity_check_passes(tmp_path):
    """integrity_check passes after migration."""
    db_path = str(tmp_path / "scan_queue.db")
    _make_old_schema_db(db_path)
    queue = ScanQueue(base_path=str(tmp_path))
    check = queue._thread_conn().execute("PRAGMA integrity_check").fetchone()
    assert str(check[0]).lower() == "ok"
    queue.close()


# ---------------------------------------------------------------------------
# Post-migration behavior
# ---------------------------------------------------------------------------

def test_same_symbol_in_different_generations_after_migration(tmp_path):
    """After migration, a symbol can exist in generation 0 and generation 1."""
    db_path = str(tmp_path / "scan_queue.db")
    _make_old_schema_db(db_path)

    queue = ScanQueue(base_path=str(tmp_path))
    assert queue.current_generation() == 0

    # Open a new generation and re-enqueue symbols (including old ones)
    result = queue.rebuild(
        ["BTC/USDT:USDT", "ETH/USDT:USDT", "XRP/USDT:USDT"],
        batch_tag="refresh_day2",
    )
    assert result["generation"] == 1

    conn = queue._thread_conn()
    rows = conn.execute(
        "SELECT symbol, scan_generation, state FROM scan_jobs "
        "ORDER BY symbol, scan_generation"
    ).fetchall()

    # BTC exists in gen 0 (done) and gen 1 (pending)
    gen0 = [r for r in rows if r[1] == 0]
    gen1 = [r for r in rows if r[1] == 1]
    assert any(r[0] == "BTC/USDT:USDT" and r[2] == DONE for r in gen0)
    assert any(r[0] == "BTC/USDT:USDT" and r[2] == PENDING for r in gen1)
    assert any(r[0] == "XRP/USDT:USDT" and r[1] == 1 for r in gen1)
    queue.close()


def test_progress_reports_current_generation_after_migration(tmp_path):
    """progress() reports the current generation after migration + new period."""
    db_path = str(tmp_path / "scan_queue.db")
    _make_old_schema_db(db_path)

    queue = ScanQueue(base_path=str(tmp_path))
    queue.rebuild(["BTC/USDT:USDT", "ETH/USDT:USDT"], batch_tag="day2")

    progress = queue.progress()  # default = current generation
    assert progress["generation"] == 1
    assert progress["total"] == 2
    assert progress["pending"] == 2

    gen0_progress = queue.progress(generation=0)
    assert gen0_progress["generation"] == 0
    assert gen0_progress["done"] == 1  # BTC was done in gen 0
    assert gen0_progress["pending"] == 1  # ETH was pending in gen 0
    queue.close()


def test_claim_next_scans_only_current_generation(tmp_path):
    """claim_next only claims from the current generation after migration."""
    db_path = str(tmp_path / "scan_queue.db")
    _make_old_schema_db(db_path)

    queue = ScanQueue(base_path=str(tmp_path))
    queue.rebuild(["BTC/USDT:USDT", "ETH/USDT:USDT"], batch_tag="day2")

    # ETH is pending in gen 1; claim it
    job = queue.claim_next("w1")
    assert job["symbol"] == "ETH/USDT:USDT" or job["symbol"] == "BTC/USDT:USDT"
    queue.close()


# ---------------------------------------------------------------------------
# Fresh database (no migration needed)
# ---------------------------------------------------------------------------

def test_fresh_database_uses_composite_pk_directly(tmp_path):
    """A brand-new queue already has composite PK, no migration needed."""
    queue = ScanQueue(base_path=str(tmp_path))
    conn = queue._thread_conn()
    pk_cols = [
        row[1] for row in conn.execute("PRAGMA table_info(scan_jobs)")
        if row[5] > 0
    ]
    assert pk_cols == ["symbol", "scan_generation"]
    assert queue.current_generation() == 0
    queue.close()
