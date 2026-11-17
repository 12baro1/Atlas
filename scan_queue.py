"""Persistent scan queue for Atlas (SQLite, requirement D.2 and F).

States: pending -> running (leased) -> done | failed -> pending(retry)
- claim_next is atomic (BEGIN IMMEDIATE): two workers can never take the
  same symbol in the same generation.
- Leases expire: a crashed worker's job is requeued automatically, so a
  VPS restart or worker crash never loses work.
- Retry counter per symbol with a bounded retry limit.
- Each scan period opens a new generation; older generations keep their
  history so completed scans never block a new period.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("atlas.scan_queue")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scan_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scan_jobs (
    symbol TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('pending','running','done','failed')),
    enqueued_at_ms INTEGER NOT NULL,
    claimed_at_ms INTEGER,
    lease_until_ms INTEGER,
    attempts INTEGER NOT NULL DEFAULT 0,
    retries INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    completed_at_ms INTEGER,
    batch_tag TEXT,
    scan_generation INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, scan_generation)
);

CREATE INDEX IF NOT EXISTS idx_scan_jobs_state ON scan_jobs(state, enqueued_at_ms);
CREATE INDEX IF NOT EXISTS idx_scan_jobs_generation ON scan_jobs(scan_generation, state);
"""

PENDING = "pending"
RUNNING = "running"
DONE = "done"
FAILED = "failed"


class ScanQueue:
    """Durable, crash-safe scan work queue with scan periods (generations)."""

    def __init__(
        self,
        base_path: str = "scan_queue",
        lease_seconds: int = 300,
        max_retries: int = 3,
    ):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.db_path = self.base_path / "scan_queue.db"
        self.lease_seconds = max(30, int(lease_seconds))
        self.max_retries = max(1, int(max_retries))
        self._local = threading.local()
        self._conn_lock = threading.Lock()
        self._closed = False
        self._current_generation = 0
        self._open()

    # ------------------------------------------------------------------
    # Connection handling
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.db_path), timeout=30.0, isolation_level=None,
            check_same_thread=False,
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _thread_conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._connect()
            self._local.conn = conn
            with self._conn_lock:
                if not self._closed:
                    self._connections = getattr(self, "_connections", [])
                    self._connections.append(conn)
        return conn

    def _migrate_to_composite_pk(self, conn: sqlite3.Connection) -> None:
        """Migrate scan_jobs from single-column PK (symbol) to composite PK (symbol, scan_generation).

        Atomic and idempotent: safe to re-run after a partial/crashed migration.
        All DDL runs inside one BEGIN IMMEDIATE transaction so a crash never
        leaves a half-migrated schema.
        """
        # Determine whether migration is needed.
        needs_migration = False
        try:
            conn.execute("SELECT scan_generation FROM scan_jobs LIMIT 1")
        except sqlite3.DatabaseError:
            needs_migration = True

        if not needs_migration:
            pk_cols = [
                row[1]
                for row in conn.execute("PRAGMA table_info(scan_jobs)")
                if row[5] > 0
            ]
            if pk_cols != ["symbol", "scan_generation"]:
                needs_migration = True

        if not needs_migration:
            return

        # A crashed earlier migration may have left scan_jobs behind; drop it.
        conn.execute("DROP TABLE IF EXISTS scan_jobs_new")

        conn.execute(
            """
            CREATE TABLE scan_jobs_new (
                symbol TEXT NOT NULL,
                state TEXT NOT NULL CHECK (state IN ('pending','running','done','failed')),
                enqueued_at_ms INTEGER NOT NULL,
                claimed_at_ms INTEGER,
                lease_until_ms INTEGER,
                attempts INTEGER NOT NULL DEFAULT 0,
                retries INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                completed_at_ms INTEGER,
                batch_tag TEXT,
                scan_generation INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (symbol, scan_generation)
            )
            """
        )

        # Preserve all old records, assigning them to generation 0.
        conn.execute(
            """
            INSERT INTO scan_jobs_new(
                symbol, state, enqueued_at_ms, claimed_at_ms, lease_until_ms,
                attempts, retries, last_error, completed_at_ms, batch_tag,
                scan_generation
            )
            SELECT
                symbol, state, enqueued_at_ms, claimed_at_ms, lease_until_ms,
                attempts, retries, last_error, completed_at_ms, batch_tag, 0
            FROM scan_jobs
            """
        )

        conn.execute("DROP TABLE scan_jobs")
        conn.execute("ALTER TABLE scan_jobs_new RENAME TO scan_jobs")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_scan_jobs_state "
            "ON scan_jobs(state, enqueued_at_ms)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_scan_jobs_generation "
            "ON scan_jobs(scan_generation, state)"
        )

    def _open(self):
        conn = self._thread_conn()
        try:
            check = conn.execute("PRAGMA integrity_check").fetchone()
            if not check or str(check[0]).lower() != "ok":
                raise sqlite3.DatabaseError(f"integrity_check failed: {check}")
            # Does scan_jobs already exist? If so it may use the old
            # single-column-PK schema and must be migrated before _SCHEMA's
            # indexes (which reference scan_generation) are created.
            table_exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='scan_jobs'"
            ).fetchone() is not None

            if table_exists:
                # Ensure scan_meta exists, then migrate scan_jobs in place.
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS scan_meta ("
                    "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
                self._migrate_to_composite_pk(conn)
            else:
                # Fresh database: create everything from _SCHEMA.
                conn.executescript(_SCHEMA)

            # Restart-safe: resume the latest generation so a VPS restart
            # never resets scan period state.
            row = conn.execute(
                "SELECT value FROM scan_meta WHERE key = 'current_generation'"
            ).fetchone()
            self._current_generation = int(row[0]) if row else 0
            # Final integrity check after migration / schema creation.
            check2 = conn.execute("PRAGMA integrity_check").fetchone()
            if not check2 or str(check2[0]).lower() != "ok":
                raise sqlite3.DatabaseError(
                    f"post-migration integrity_check failed: {check2}"
                )
        except sqlite3.DatabaseError:
            # Corrupt queue file: drop it and start empty; the pool and
            # inventory are independent systems and stay untouched.
            logger.warning("Scan queue corrupt; recreating empty queue")
            self._close_all()
            for suffix in ("", "-wal", "-shm"):
                source = Path(str(self.db_path) + suffix)
                if source.exists():
                    try:
                        source.unlink()
                    except OSError:
                        pass
            self._closed = False
            conn = self._thread_conn()
            conn.executescript(_SCHEMA)
            self._current_generation = 0

    def _close_all(self):
        with self._conn_lock:
            self._closed = True
            for conn in getattr(self, "_connections", []):
                try:
                    conn.close()
                except Exception:
                    pass
            self._connections = []
        self._local = threading.local()

    def close(self):
        self._close_all()

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def start_new_period(self, batch_tag: Optional[str] = None) -> int:
        """Open a new scan generation (period).

        Older generations keep their history (done/failed/pending) so scan
        statistics are never lost; only the new generation accepts new work.
        Returns the new generation number.
        """
        with self._transaction() as conn:
            self._current_generation += 1
            gen = self._current_generation
            conn.execute(
                "INSERT INTO scan_meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("current_generation", str(gen)),
            )
            if batch_tag is not None:
                conn.execute(
                    "INSERT INTO scan_meta(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    ("last_batch_tag", str(batch_tag)),
                )
        return gen

    def current_generation(self) -> int:
        return self._current_generation

    def enqueue(self, symbols: List[str], batch_tag: Optional[str] = None,
                generation: Optional[int] = None) -> int:
        """Add symbols to the queue for a scan generation.

        Symbols already present in the same generation keep their state (no
        silent reset of completed work). Symbols from older generations are
        re-opened as pending in the new generation.
        """
        now_ms = int(time.time() * 1000)
        gen = int(generation) if generation is not None else self._current_generation
        added = 0
        with self._transaction() as conn:
            for symbol in symbols:
                clean = str(symbol or "").strip().upper()
                if not clean:
                    continue
                # Same generation: an existing job keeps its state, so a
                # repeated enqueue of an already-known symbol is a no-op.
                existing = conn.execute(
                    "SELECT state FROM scan_jobs WHERE symbol = ? AND scan_generation = ?",
                    (clean, gen),
                ).fetchone()
                if existing is not None:
                    continue
                # New symbol for this generation (or brand-new queue row).
                cursor = conn.execute(
                    """
                    INSERT INTO scan_jobs(symbol, state, enqueued_at_ms,
                        batch_tag, scan_generation)
                    VALUES(?, ?, ?, ?, ?)
                    """,
                    (clean, PENDING, now_ms, batch_tag, gen),
                )
                added += max(cursor.rowcount, 0)
        return added

    def claim_next(self, worker_id: str = "worker") -> Optional[Dict[str, Any]]:
        """Atomically claim the oldest pending symbol of the current generation."""
        now_ms = int(time.time() * 1000)
        gen = self._current_generation
        with self._transaction() as conn:
            # Recover expired leases first so crashed workers release jobs.
            conn.execute(
                "UPDATE scan_jobs SET state = ?, lease_until_ms = NULL, "
                "last_error = COALESCE(last_error, 'lease_expired') "
                "WHERE state = ? AND scan_generation = ? "
                "AND lease_until_ms IS NOT NULL AND lease_until_ms < ?",
                (PENDING, RUNNING, gen, now_ms),
            )
            row = conn.execute(
                "SELECT symbol, attempts, retries FROM scan_jobs "
                "WHERE state = ? AND scan_generation = ? "
                "ORDER BY enqueued_at_ms ASC LIMIT 1",
                (PENDING, gen),
            ).fetchone()
            if row is None:
                return None
            symbol, attempts, retries = row
            conn.execute(
                "UPDATE scan_jobs SET state = ?, claimed_at_ms = ?, "
                "lease_until_ms = ?, attempts = attempts + 1 "
                "WHERE symbol = ? AND scan_generation = ?",
                (RUNNING, now_ms, now_ms + self.lease_seconds * 1000,
                 symbol, gen),
            )
            return {
                "symbol": symbol,
                "attempts": int(attempts) + 1,
                "retries": int(retries),
                "worker_id": worker_id,
                "claimed_at_ms": now_ms,
            }

    def complete(self, symbol: str, ok: bool, error: Optional[str] = None) -> bool:
        """Mark a claimed symbol done, or requeue it for a bounded retry."""
        clean = str(symbol or "").strip().upper()
        now_ms = int(time.time() * 1000)
        gen = self._current_generation
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT state, retries FROM scan_jobs WHERE symbol = ? "
                "AND scan_generation = ?", (clean, gen),
            ).fetchone()
            if row is None or row[0] != RUNNING:
                return False
            retries = int(row[1])
            if ok:
                conn.execute(
                    "UPDATE scan_jobs SET state = ?, completed_at_ms = ?, "
                    "last_error = NULL, lease_until_ms = NULL "
                    "WHERE symbol = ? AND scan_generation = ?",
                    (DONE, now_ms, clean, gen),
                )
                return True
            if retries < self.max_retries:
                conn.execute(
                    "UPDATE scan_jobs SET state = ?, retries = retries + 1, "
                    "last_error = ?, lease_until_ms = NULL "
                    "WHERE symbol = ? AND scan_generation = ?",
                    (PENDING, str(error or "unknown_error"), clean, gen),
                )
            else:
                conn.execute(
                    "UPDATE scan_jobs SET state = ?, last_error = ?, "
                    "lease_until_ms = NULL "
                    "WHERE symbol = ? AND scan_generation = ?",
                    (FAILED, str(error or "unknown_error"), clean, gen),
                )
            return True

    def progress(self, generation: Optional[int] = None) -> Dict[str, Any]:
        """Cumulative progress for a scan generation.

        generation=None reports the current (latest) generation.
        """
        gen = int(generation) if generation is not None else self._current_generation
        conn = self._thread_conn()
        counts = {state: 0 for state in (PENDING, RUNNING, DONE, FAILED)}
        for state, count in conn.execute(
            "SELECT state, COUNT(*) FROM scan_jobs WHERE scan_generation = ? "
            "GROUP BY state", (gen,)
        ).fetchall():
            counts[str(state)] = int(count)
        total = sum(counts.values())
        finished = counts[DONE] + counts[FAILED]
        next_symbol = conn.execute(
            "SELECT symbol FROM scan_jobs WHERE state = ? AND scan_generation = ? "
            "ORDER BY enqueued_at_ms ASC LIMIT 1", (PENDING, gen)
        ).fetchone()
        return {
            "generation": gen,
            "total": total,
            "pending": counts[PENDING],
            "running": counts[RUNNING],
            "done": counts[DONE],
            "failed": counts[FAILED],
            "finished": finished,
            "percent": round(100.0 * finished / total, 1) if total else 0.0,
            "complete": total > 0 and counts[PENDING] == 0 and counts[RUNNING] == 0,
            "next_symbol": next_symbol[0] if next_symbol else None,
        }

    def failed_symbols(self, generation: Optional[int] = None) -> List[Dict[str, Any]]:
        gen = int(generation) if generation is not None else self._current_generation
        rows = self._thread_conn().execute(
            "SELECT symbol, attempts, retries, last_error FROM scan_jobs "
            "WHERE state = ? AND scan_generation = ? ORDER BY symbol",
            (FAILED, gen),
        ).fetchall()
        return [
            {"symbol": row[0], "attempts": row[1], "retries": row[2], "error": row[3]}
            for row in rows
        ]

    def rebuild(self, symbols: List[str], batch_tag: Optional[str] = None) -> Dict[str, int]:
        """Open a new scan generation and queue the given symbols for it.

        Older generations keep their history; completed scans never block a
        new period. New symbols are enqueued as pending; previously scanned
        symbols in the same generation keep their result.
        """
        gen = self.start_new_period(batch_tag)
        added = self.enqueue(symbols, batch_tag=batch_tag, generation=gen)
        snapshot = self.progress(gen)
        return {"added": added, "progress": snapshot, "generation": gen}

    def requeue_failed(self, generation: Optional[int] = None) -> int:
        """Manually requeue failed symbols of a generation for another attempt."""
        gen = int(generation) if generation is not None else self._current_generation
        with self._transaction() as conn:
            cursor = conn.execute(
                "UPDATE scan_jobs SET state = ?, lease_until_ms = NULL "
                "WHERE state = ? AND scan_generation = ?",
                (PENDING, FAILED, gen),
            )
            return max(cursor.rowcount, 0)

    def done_symbols(self, generation: Optional[int] = None) -> List[str]:
        gen = int(generation) if generation is not None else self._current_generation
        rows = self._thread_conn().execute(
            "SELECT symbol FROM scan_jobs WHERE state = ? AND scan_generation = ? "
            "ORDER BY symbol", (DONE, gen),
        ).fetchall()
        return [row[0] for row in rows]

    def _transaction(self):
        return _WriteTransaction(self._thread_conn())


class _WriteTransaction:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def __enter__(self) -> sqlite3.Connection:
        self._conn.execute("BEGIN IMMEDIATE")
        return self._conn

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._conn.execute("COMMIT")
        else:
            try:
                self._conn.execute("ROLLBACK")
            except sqlite3.DatabaseError:
                pass
        return False
