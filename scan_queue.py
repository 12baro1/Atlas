"""Persistent scan queue for Atlas (SQLite, requirement D.2 and F).

States: pending -> running (leased) -> done | failed -> pending(retry)
- claim_next is atomic (BEGIN IMMEDIATE): two workers can never take the
  same symbol.
- Leases expire: a crashed worker's job is requeued automatically, so a
  VPS restart or worker crash never loses work.
- Retry counter per symbol with a bounded retry limit.
- Completed work is never deleted: progress reports are cumulative for the
  current scan period, and rebuilding the universe adds new symbols
  without resetting existing state.
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
CREATE TABLE IF NOT EXISTS scan_jobs (
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

CREATE INDEX IF NOT EXISTS idx_scan_jobs_state ON scan_jobs(state, enqueued_at_ms);
"""

PENDING = "pending"
RUNNING = "running"
DONE = "done"
FAILED = "failed"


class ScanQueue:
    """Durable, crash-safe scan work queue."""

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

    def _open(self):
        conn = self._thread_conn()
        try:
            check = conn.execute("PRAGMA integrity_check").fetchone()
            if not check or str(check[0]).lower() != "ok":
                raise sqlite3.DatabaseError(f"integrity_check failed: {check}")
            conn.executescript(_SCHEMA)
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

    def enqueue(self, symbols: List[str], batch_tag: Optional[str] = None) -> int:
        """Add symbols to the queue; existing symbols keep their state."""
        now_ms = int(time.time() * 1000)
        added = 0
        with self._transaction() as conn:
            for symbol in symbols:
                clean = str(symbol or "").strip().upper()
                if not clean:
                    continue
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO scan_jobs(symbol, state, enqueued_at_ms, "
                    "batch_tag) VALUES(?, ?, ?, ?)",
                    (clean, PENDING, now_ms, batch_tag),
                )
                added += max(cursor.rowcount, 0)
        return added

    def claim_next(self, worker_id: str = "worker") -> Optional[Dict[str, Any]]:
        """Atomically claim the oldest pending symbol (or an expired lease)."""
        now_ms = int(time.time() * 1000)
        with self._transaction() as conn:
            # Recover expired leases first so crashed workers release jobs.
            conn.execute(
                "UPDATE scan_jobs SET state = ?, lease_until_ms = NULL, "
                "last_error = COALESCE(last_error, 'lease_expired') "
                "WHERE state = ? AND lease_until_ms IS NOT NULL AND lease_until_ms < ?",
                (PENDING, RUNNING, now_ms),
            )
            row = conn.execute(
                "SELECT symbol, attempts, retries FROM scan_jobs "
                "WHERE state = ? ORDER BY enqueued_at_ms ASC LIMIT 1",
                (PENDING,),
            ).fetchone()
            if row is None:
                return None
            symbol, attempts, retries = row
            conn.execute(
                "UPDATE scan_jobs SET state = ?, claimed_at_ms = ?, "
                "lease_until_ms = ?, attempts = attempts + 1 WHERE symbol = ?",
                (RUNNING, now_ms, now_ms + self.lease_seconds * 1000, symbol),
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
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT state, retries FROM scan_jobs WHERE symbol = ?", (clean,)
            ).fetchone()
            if row is None or row[0] != RUNNING:
                return False
            retries = int(row[1])
            if ok:
                conn.execute(
                    "UPDATE scan_jobs SET state = ?, completed_at_ms = ?, "
                    "last_error = NULL, lease_until_ms = NULL WHERE symbol = ?",
                    (DONE, now_ms, clean),
                )
                return True
            if retries < self.max_retries:
                conn.execute(
                    "UPDATE scan_jobs SET state = ?, retries = retries + 1, "
                    "last_error = ?, lease_until_ms = NULL WHERE symbol = ?",
                    (PENDING, str(error or "unknown_error"), clean),
                )
            else:
                conn.execute(
                    "UPDATE scan_jobs SET state = ?, last_error = ?, "
                    "lease_until_ms = NULL WHERE symbol = ?",
                    (FAILED, str(error or "unknown_error"), clean),
                )
            return True

    def progress(self) -> Dict[str, Any]:
        """Cumulative progress for the current queue contents."""
        conn = self._thread_conn()
        counts = {state: 0 for state in (PENDING, RUNNING, DONE, FAILED)}
        for state, count in conn.execute(
            "SELECT state, COUNT(*) FROM scan_jobs GROUP BY state"
        ).fetchall():
            counts[str(state)] = int(count)
        total = sum(counts.values())
        finished = counts[DONE] + counts[FAILED]
        next_symbol = conn.execute(
            "SELECT symbol FROM scan_jobs WHERE state = ? "
            "ORDER BY enqueued_at_ms ASC LIMIT 1", (PENDING,)
        ).fetchone()
        return {
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

    def failed_symbols(self) -> List[Dict[str, Any]]:
        rows = self._thread_conn().execute(
            "SELECT symbol, attempts, retries, last_error FROM scan_jobs "
            "WHERE state = ? ORDER BY symbol", (FAILED,)
        ).fetchall()
        return [
            {"symbol": row[0], "attempts": row[1], "retries": row[2], "error": row[3]}
            for row in rows
        ]

    def rebuild(self, symbols: List[str], batch_tag: Optional[str] = None) -> Dict[str, int]:
        """Add the current universe to the queue WITHOUT resetting state.

        New symbols are enqueued as pending; previously scanned symbols keep
        their result so a completed scan is never silently thrown away.
        """
        added = self.enqueue(symbols, batch_tag=batch_tag)
        snapshot = self.progress()
        return {"added": added, "progress": snapshot}

    def requeue_failed(self) -> int:
        """Manually requeue failed symbols for another bounded attempt."""
        with self._transaction() as conn:
            cursor = conn.execute(
                "UPDATE scan_jobs SET state = ?, lease_until_ms = NULL "
                "WHERE state = ?",
                (PENDING, FAILED),
            )
            return max(cursor.rowcount, 0)

    def done_symbols(self) -> List[str]:
        rows = self._thread_conn().execute(
            "SELECT symbol FROM scan_jobs WHERE state = ? ORDER BY symbol", (DONE,)
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
