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

import json
from contextlib import nullcontext
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlite_connections import ThreadConnections

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

CREATE TABLE IF NOT EXISTS cycle_results(generation INTEGER, symbol TEXT, payload TEXT NOT NULL, PRIMARY KEY(generation,symbol));
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
        self._connections = ThreadConnections()
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
        return self._connections.get(self._connect)

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
                with self._transaction():
                    self._migrate_to_composite_pk(conn)
            conn.executescript(_SCHEMA)

            # Restart-safe: resume the latest generation so a VPS restart
            # never resets scan period state.
            # Final integrity check after migration / schema creation.
            check2 = conn.execute("PRAGMA integrity_check").fetchone()
            if not check2 or str(check2[0]).lower() != "ok":
                raise sqlite3.DatabaseError(
                    f"post-migration integrity_check failed: {check2}"
                )
        except sqlite3.DatabaseError:
            # A lock or migration error is not evidence of corruption.
            # Preserve the database, WAL and history for retry or recovery.
            self._connections.close()
            raise


    def close(self):
        self._connections.close()

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
            gen = self.current_generation() + 1
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

    @property
    def _current_generation(self) -> int:
        row = self._thread_conn().execute(
            "SELECT value FROM scan_meta WHERE key='current_generation'"
        ).fetchone()
        return int(row[0]) if row else 0

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

    def requeue_completed(
        self, symbols: List[str], batch_tag: Optional[str] = None
    ) -> int:
        """Reopen completed/failed jobs for live setup revalidation.

        Pending and running jobs are left untouched. In particular, a worker
        already analyzing a symbol is never duplicated or interrupted.
        """
        clean_symbols = list(dict.fromkeys(
            str(symbol or "").strip().upper()
            for symbol in symbols if str(symbol or "").strip()
        ))
        if not clean_symbols:
            return 0
        now_ms = int(time.time() * 1000)
        gen = self._current_generation
        requeued = 0
        with self._transaction() as conn:
            for symbol in clean_symbols:
                cursor = conn.execute(
                    """
                    UPDATE scan_jobs
                    SET state = ?, enqueued_at_ms = ?, claimed_at_ms = NULL,
                        lease_until_ms = NULL, retries = 0, last_error = NULL,
                        completed_at_ms = NULL, batch_tag = ?
                    WHERE symbol = ? AND scan_generation = ?
                      AND state IN (?, ?)
                    """,
                    (PENDING, now_ms, batch_tag, symbol, gen, DONE, FAILED),
                )
                requeued += max(cursor.rowcount, 0)
        return requeued

    def claim_next(self, worker_id: str = "worker") -> Optional[Dict[str, Any]]:
        """Atomically claim the oldest pending symbol of the current generation."""
        now_ms = int(time.time() * 1000)
        with self._transaction() as conn:
            # Recover expired leases first so crashed workers release jobs.
            gen = self.current_generation()
            conn.execute(
                "UPDATE scan_jobs SET state = CASE WHEN retries >= ? THEN ? ELSE ? END, "
                "retries = MIN(retries + 1, ?), lease_until_ms = NULL, last_error = 'lease_expired' "
                "WHERE state = ? AND scan_generation = ? "
                "AND lease_until_ms IS NOT NULL AND lease_until_ms < ?",
                (self.max_retries, FAILED, PENDING, self.max_retries, RUNNING, gen, now_ms),
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
                "generation": gen,
                "claimed_at_ms": now_ms,
            }

    def complete(self, symbol: str, ok: bool, error: Optional[str] = None,
                 *, claim: Optional[Dict[str, Any]] = None, result=None, stage_failure=False) -> bool:
        """Mark a claimed symbol done, or requeue it for a bounded retry."""
        clean = str(symbol or "").strip().upper()
        now_ms = int(time.time() * 1000)
        gen = claim["generation"] if claim is not None else self.current_generation()
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT state, retries, attempts FROM scan_jobs WHERE symbol = ? "
                "AND scan_generation = ?", (clean, gen),
            ).fetchone()
            if row is None or row[0] != RUNNING:
                return False
            if claim is not None and (claim["symbol"] != clean or row[2] != claim["attempts"]):
                return False
            retries = int(row[1])
            if ok:
                if result is not None:
                    conn.execute("INSERT OR REPLACE INTO cycle_results VALUES(?,?,?)",
                                 (gen, clean, json.dumps(result, allow_nan=False)))
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
                if stage_failure:
                    # This symbol reached a terminal state without an observation.
                    conn.execute("INSERT OR IGNORE INTO cycle_results VALUES(?,?,?)",
                                 (gen, clean, "null"))
                conn.execute(
                    "UPDATE scan_jobs SET state = ?, last_error = ?, "
                    "lease_until_ms = NULL "
                    "WHERE symbol = ? AND scan_generation = ?",
                    (FAILED, str(error or "unknown_error"), clean, gen),
                )
            return True

    def restore_unstaged_jobs(self, generation):
        """Old workers could mark a job done before cycle_results existed."""
        with self._transaction() as conn:
            return conn.execute("""
                UPDATE scan_jobs SET state='pending', completed_at_ms=NULL, lease_until_ms=NULL
                WHERE scan_generation=? AND state='done' AND NOT EXISTS (
                    SELECT 1 FROM cycle_results r WHERE r.generation=scan_jobs.scan_generation
                    AND r.symbol=scan_jobs.symbol)
            """, (generation,)).rowcount

    def cycle_results(self, generation):
        rows = self._thread_conn().execute(
            "SELECT payload FROM cycle_results WHERE generation=? AND payload!='null' ORDER BY symbol", (generation,),
        )
        return [json.loads(row[0]) for row in rows]

    def staged_batch(self, generation, after, limit):
        # Staged rows stay in the queue until final publication. Rowid provides
        # insertion order even when several jobs finish in the same millisecond.
        rows = self._thread_conn().execute(
            "SELECT rowid, payload FROM cycle_results WHERE generation=? AND rowid>? "
            "ORDER BY rowid LIMIT ?", (generation, after, limit),
        )
        return [(cursor, json.loads(payload)) for cursor, payload in rows]

    def discard_applied_results(self, generation):
        with self._transaction() as conn:
            conn.execute("DELETE FROM cycle_results WHERE generation<=?", (generation,))

    def generation_symbols(self, generation: Optional[int] = None) -> List[str]:
        """Return every symbol recorded in a generation, regardless of state."""
        gen = int(generation) if generation is not None else self._current_generation
        rows = self._thread_conn().execute(
            "SELECT symbol FROM scan_jobs WHERE scan_generation = ? ORDER BY symbol",
            (gen,),
        ).fetchall()
        return [str(row[0]) for row in rows]

    def set_generation_ranking(self, symbols: List[str], source: str,
                               generation: Optional[int] = None) -> None:
        """Persist the ranked universe used to build the active generation."""
        gen = int(generation) if generation is not None else self._current_generation
        payload = json.dumps([str(symbol) for symbol in symbols], separators=(",", ":"))
        with self._transaction() as conn:
            for key, value in (
                (f"generation_{gen}_ranked_symbols", payload),
                (f"generation_{gen}_ranking_source", str(source or "unknown")),
            ):
                conn.execute(
                    "INSERT INTO scan_meta(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, value),
                )

    def generation_ranking(self, generation: Optional[int] = None) -> Dict[str, Any]:
        """Read the persisted ranked universe metadata for the active generation."""
        gen = int(generation) if generation is not None else self._current_generation
        rows = dict(self._thread_conn().execute(
            "SELECT key, value FROM scan_meta WHERE key IN (?, ?)",
            (f"generation_{gen}_ranked_symbols", f"generation_{gen}_ranking_source"),
        ).fetchall())
        try:
            symbols = json.loads(rows.get(f"generation_{gen}_ranked_symbols", "[]"))
        except (TypeError, ValueError):
            symbols = []
        return {
            "symbols": symbols if isinstance(symbols, list) else [],
            "ranking_source": rows.get(f"generation_{gen}_ranking_source"),
        }

    def reorder_pending(self, ranked_symbols: List[str]) -> int:
        """Prioritize pending jobs by turnover rank without changing job states."""
        rank = {str(symbol): index for index, symbol in enumerate(ranked_symbols)}
        now_ms = int(time.time() * 1000)
        gen = self._current_generation
        with self._transaction() as conn:
            rows = conn.execute(
                "SELECT symbol FROM scan_jobs WHERE state = ? AND scan_generation = ?",
                (PENDING, gen),
            ).fetchall()
            ordered = sorted(
                (str(row[0]) for row in rows),
                key=lambda symbol: (rank.get(symbol, len(rank)), symbol),
            )
            for index, symbol in enumerate(ordered):
                conn.execute(
                    "UPDATE scan_jobs SET enqueued_at_ms = ? "
                    "WHERE symbol = ? AND state = ? AND scan_generation = ?",
                    (now_ms + index, symbol, PENDING, gen),
                )
        return len(ordered)

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

    def rebuild(self, symbols: List[str], batch_tag: Optional[str] = None,
                *, preserve_unfinished: bool = False, ranking_source=None) -> Dict[str, Any]:
        """Open a new scan generation and queue the given symbols for it.

        Older generations keep their history; completed scans never block a
        new period. New symbols are enqueued as pending; previously scanned
        symbols in the same generation keep their result.
        """
        ordered = list(dict.fromkeys(str(s).strip().upper() for s in symbols if s and str(s).strip()))
        with self._transaction() as conn:
            row = conn.execute("SELECT value FROM scan_meta WHERE key='current_generation'").fetchone()
            gen = int(row[0]) if row else 0
            unfinished = conn.execute(
                "SELECT 1 FROM scan_jobs WHERE scan_generation=? AND state IN ('pending','running') LIMIT 1",
                (gen,),
            ).fetchone()
            rebuilt = bool(ordered) and not (preserve_unfinished and unfinished)
            added = 0
            if rebuilt:
                gen += 1
                conn.execute("INSERT OR REPLACE INTO scan_meta VALUES ('current_generation', ?)", (str(gen),))
                if batch_tag is not None:
                    conn.execute("INSERT OR REPLACE INTO scan_meta VALUES ('last_batch_tag', ?)", (batch_tag,))
                now = int(time.time() * 1000)
                conn.executemany(
                    "INSERT INTO scan_jobs(symbol,state,enqueued_at_ms,batch_tag,scan_generation) "
                    "VALUES (?, 'pending', ?, ?, ?)",
                    ((symbol, now + index, batch_tag, gen) for index, symbol in enumerate(ordered)),
                )
                added = len(ordered)
                if ranking_source is not None:
                    self.set_generation_ranking(ordered, ranking_source, generation=gen)
        snapshot = self.progress(gen)
        return {"added": added, "progress": snapshot, "generation": gen, "rebuilt": rebuilt}

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

    def extend_ranked(self, symbols, batch_tag, source, revalidate=()):
        """Commit new jobs, reopened jobs and the ordering workers will see together."""
        with self._transaction():
            added = self.enqueue(symbols, batch_tag=batch_tag)
            reopened = self.requeue_completed(revalidate, batch_tag=batch_tag)
            existing = self.generation_ranking()["symbols"] + self.generation_symbols()
            ordered = list(dict.fromkeys([*symbols, *existing]))
            self.reorder_pending(ordered)
            self.set_generation_ranking(ordered, source)
            return added, reopened

    def _transaction(self):
        conn = self._thread_conn()
        # All callers propagate exceptions to the owning write transaction.
        return nullcontext(conn) if conn.in_transaction else _WriteTransaction(conn)


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
