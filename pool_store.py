"""SQLite-backed persistent storage for the Atlas opportunity pool.

Design (PR #173, requirement E):
- WAL journal mode + busy_timeout: safe concurrent access from multiple
  workers (scanner, Telegram, TUI) on one file.
- Every save is one BEGIN IMMEDIATE transaction: a crash mid-write leaves
  the previous consistent state, never a half-written pool.
- setup_id is the primary key: re-running the JSON migration can never
  produce duplicate records (idempotent migration).
- history rows carry a natural unique key (setup_id, status, closed_at_ms)
  so archival retries stay idempotent.
- integrity_check on open; a corrupt database file is moved aside (kept for
  forensics) and a fresh one is created instead of crashing the service.
- Online backup API for consistent hot backups.
"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("atlas.pool_store")

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pool_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS setups (
    setup_id TEXT NOT NULL,
    pool TEXT NOT NULL CHECK (pool IN ('candidates', 'validated', 'active')),
    symbol TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL DEFAULT 0,
    updated_at_ms INTEGER NOT NULL DEFAULT 0,
    payload TEXT NOT NULL,
    PRIMARY KEY (setup_id, pool)
);

CREATE INDEX IF NOT EXISTS idx_setups_pool ON setups(pool);
CREATE INDEX IF NOT EXISTS idx_setups_symbol ON setups(symbol);
CREATE INDEX IF NOT EXISTS idx_setups_status ON setups(status);

CREATE TABLE IF NOT EXISTS history (
    archive_id INTEGER PRIMARY KEY AUTOINCREMENT,
    setup_id TEXT NOT NULL,
    status TEXT NOT NULL,
    closed_at_ms INTEGER NOT NULL DEFAULT 0,
    reason TEXT,
    payload TEXT NOT NULL,
    UNIQUE (setup_id, status, closed_at_ms)
);

CREATE INDEX IF NOT EXISTS idx_history_closed ON history(closed_at_ms);
"""


class PoolStore:
    """Transaction-safe SQLite persistence for one opportunity pool directory.

    Each thread gets its own connection (WAL + busy_timeout), so scanner,
    Telegram and TUI workers can write concurrently without interleaving
    another thread's transaction.
    """

    def __init__(self, directory: str):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.db_path = self.directory / "pool_state.db"
        self._local = threading.local()
        self._all_conns: List[sqlite3.Connection] = []
        self._conn_lock = threading.Lock()
        self._closed = False
        self._open()

    # ------------------------------------------------------------------
    # Connection handling and corruption recovery
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        # check_same_thread=False is safe because every thread uses its own
        # connection object; write safety comes from BEGIN IMMEDIATE plus
        # busy_timeout, not from the connection's own thread check.
        conn = sqlite3.connect(
            str(self.db_path), timeout=30.0, isolation_level=None,
            check_same_thread=False,
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _thread_conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._connect()
            self._local.conn = conn
            with self._conn_lock:
                if not self._closed:
                    self._all_conns.append(conn)
        return conn

    def _open(self):
        try:
            conn = self._thread_conn()
            # A corrupt file must never take the whole service down.
            check = conn.execute("PRAGMA integrity_check").fetchone()
            if not check or str(check[0]).lower() != "ok":
                raise sqlite3.DatabaseError(f"integrity_check failed: {check}")
            conn.executescript(_SCHEMA)
            self.set_meta("schema_version", str(SCHEMA_VERSION))
        except (sqlite3.DatabaseError, OSError) as exc:
            logger.error(f"Pool store damaged, recovering: {exc}")
            self._close_all()
            self._recover_corrupt_file()
            self._closed = False  # reopen after quarantine
            conn = self._thread_conn()
            conn.executescript(_SCHEMA)
            self.set_meta("schema_version", str(SCHEMA_VERSION))

    def _recover_corrupt_file(self):
        """Quarantine the corrupt DB sidecar files and start a fresh one."""
        stamp = int(time.time() * 1000)
        for suffix in ("", "-wal", "-shm"):
            source = Path(str(self.db_path) + suffix)
            if source.exists():
                quarantine = self.directory / f"pool_state.corrupt-{stamp}{suffix}"
                try:
                    shutil.move(str(source), str(quarantine))
                    logger.warning(f"Quarantined corrupt store file: {quarantine}")
                except OSError as move_exc:
                    logger.error(f"Could not quarantine {source}: {move_exc}")
                    try:
                        source.unlink()
                    except OSError:
                        pass

    # ------------------------------------------------------------------
    # Meta
    # ------------------------------------------------------------------

    def set_meta(self, key: str, value: str):
        with self._transaction() as conn:
            conn.execute(
                "INSERT INTO pool_meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )

    def get_meta(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self._thread_conn().execute(
            "SELECT value FROM pool_meta WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else default

    # ------------------------------------------------------------------
    # Transaction helper
    # ------------------------------------------------------------------

    def _transaction(self):
        return _WriteTransaction(self._thread_conn())

    # ------------------------------------------------------------------
    # Live pools
    # ------------------------------------------------------------------

    def save_pool(self, pool: str, records: Dict[str, Dict[str, Any]]) -> int:
        """Replace the stored contents of one live pool in a single transaction.

        Records present in `records` are upserted; stored ids that are absent
        were removed in memory and are deleted here, so the DB always mirrors
        the current in-memory pool exactly.
        """
        now_ms = int(time.time() * 1000)
        with self._transaction() as conn:
            stored_ids = {
                row[0]
                for row in conn.execute(
                    "SELECT setup_id FROM setups WHERE pool = ?", (pool,)
                ).fetchall()
            }
            wanted_ids = set(records.keys())
            removed = stored_ids - wanted_ids
            if removed:
                conn.executemany(
                    "DELETE FROM setups WHERE pool = ? AND setup_id = ?",
                    [(pool, sid) for sid in sorted(removed)],
                )
            for setup_id, payload in records.items():
                conn.execute(
                    "INSERT INTO setups(setup_id, pool, symbol, strategy_id, "
                    "direction, status, created_at_ms, updated_at_ms, payload) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(setup_id, pool) DO UPDATE SET "
                    "symbol=excluded.symbol, strategy_id=excluded.strategy_id, "
                    "direction=excluded.direction, status=excluded.status, "
                    "created_at_ms=excluded.created_at_ms, "
                    "updated_at_ms=excluded.updated_at_ms, "
                    "payload=excluded.payload",
                    (
                        setup_id,
                        pool,
                        str(payload.get("symbol") or ""),
                        str(payload.get("strategy_id") or ""),
                        str(payload.get("direction") or ""),
                        str(payload.get("status") or ""),
                        int(payload.get("created_at_ms") or 0),
                        int(payload.get("updated_at_ms") or now_ms),
                        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    ),
                )
        return len(records)

    def load_pool(self, pool: str) -> Dict[str, Dict[str, Any]]:
        rows = self._thread_conn().execute(
            "SELECT setup_id, payload FROM setups WHERE pool = ?", (pool,)
        ).fetchall()
        result: Dict[str, Dict[str, Any]] = {}
        for setup_id, payload in rows:
            try:
                record = json.loads(payload)
            except (TypeError, ValueError) as exc:
                logger.error(f"Skipping unreadable stored setup {setup_id}: {exc}")
                continue
            result[setup_id] = record
        return result

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def append_history(self, records: List[Dict[str, Any]]) -> int:
        """Append archived setups. Idempotent via the natural unique key."""
        if not records:
            return 0
        inserted = 0
        with self._transaction() as conn:
            for payload in records:
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO history(setup_id, status, "
                    "closed_at_ms, reason, payload) VALUES(?, ?, ?, ?, ?)",
                    (
                        str(payload.get("setup_id") or ""),
                        str(payload.get("status") or ""),
                        int(payload.get("closed_at_ms") or 0),
                        payload.get("invalidation_reason"),
                        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    ),
                )
                inserted += cursor.rowcount
        return inserted

    def load_history(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        sql = (
            "SELECT payload FROM history ORDER BY archive_id ASC"
        )
        rows = self._thread_conn().execute(sql).fetchall()
        result = []
        for (payload,) in rows:
            try:
                result.append(json.loads(payload))
            except (TypeError, ValueError):
                continue
        if limit is not None and len(result) > limit:
            result = result[-limit:]
        return result

    # ------------------------------------------------------------------
    # Migration from the legacy JSON files
    # ------------------------------------------------------------------

    def migrate_from_json(self, json_directory) -> Dict[str, int]:
        """Idempotently import legacy candidates/validated/active/history JSON.

        Uses INSERT OR IGNORE everywhere, so running it twice (e.g. after a
        restart) cannot duplicate records. Legacy files are left untouched
        until the pool decides to archive them.
        """
        directory = Path(json_directory)
        migrated = {"candidates": 0, "validated": 0, "active": 0, "history": 0}
        if not directory.exists():
            return migrated

        legacy_names = {
            "candidates": "candidates.json",
            "validated": "validated.json",
            "active": "active.json",
        }
        for pool, filename in legacy_names.items():
            path = directory / filename
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                records = data.get(pool) or {}
            except (OSError, TypeError, ValueError) as exc:
                logger.error(f"Skipping unreadable legacy file {filename}: {exc}")
                continue
            if not isinstance(records, dict) or not records:
                continue
            with self._transaction() as conn:
                for setup_id, payload in records.items():
                    cursor = conn.execute(
                        "INSERT OR IGNORE INTO setups(setup_id, pool, symbol, "
                        "strategy_id, direction, status, created_at_ms, "
                        "updated_at_ms, payload) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            str(setup_id),
                            pool,
                            str(payload.get("symbol") or ""),
                            str(payload.get("strategy_id") or ""),
                            str(payload.get("direction") or ""),
                            str(payload.get("status") or ""),
                            int(payload.get("created_at_ms") or 0),
                            int(payload.get("updated_at_ms") or 0),
                            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                        ),
                    )
                    migrated[pool] += max(cursor.rowcount, 0)

        history_path = directory / "history.json"
        if history_path.exists():
            try:
                data = json.loads(history_path.read_text(encoding="utf-8"))
                records = data.get("history") or []
            except (OSError, TypeError, ValueError) as exc:
                logger.error(f"Skipping unreadable legacy history: {exc}")
                records = []
            if isinstance(records, list) and records:
                migrated["history"] = self.append_history(records)
        return migrated

    def mark_json_migration_done(self, marker: str = "done"):
        self.set_meta("json_migration", marker)

    def json_migration_done(self) -> bool:
        return (self.get_meta("json_migration") or "") == "done"

    # ------------------------------------------------------------------
    # Backup
    # ------------------------------------------------------------------

    def backup(self, destination) -> str:
        """Consistent online backup using the SQLite backup API."""
        dest_path = Path(destination)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        if dest_path.exists():
            dest_path.unlink()
        dest = sqlite3.connect(str(dest_path))
        try:
            self._thread_conn().backup(dest)
        finally:
            dest.close()
        return str(dest_path)

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def checkpoint_wal(self):
        try:
            self._thread_conn().execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.DatabaseError as exc:
            logger.warning(f"WAL checkpoint failed: {exc}")

    def _close_all(self):
        with self._conn_lock:
            self._closed = True
            for conn in self._all_conns:
                try:
                    conn.close()
                except Exception:
                    pass
            self._all_conns = []
        self._local = threading.local()

    def close(self):
        self._close_all()


class _WriteTransaction:
    """BEGIN IMMEDIATE context manager: writes serialize across workers."""

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
