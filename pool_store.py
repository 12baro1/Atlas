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
from contextlib import nullcontext
import logging
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlite_connections import ThreadConnections

logger = logging.getLogger("atlas.pool_store")

import telegram_tracking

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
        self._connections = ThreadConnections()
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
        return self._connections.get(self._connect)

    def _open(self):
        try:
            conn = self._thread_conn()
            # A corrupt file must never take the whole service down.
            check = conn.execute("PRAGMA integrity_check").fetchone()
            if not check or str(check[0]).lower() != "ok":
                raise sqlite3.DatabaseError(f"integrity_check failed: {check}")
            conn.executescript(_SCHEMA + telegram_tracking.SCHEMA)
            self.set_meta("schema_version", str(SCHEMA_VERSION))
        except (sqlite3.OperationalError, OSError):
            self._connections.close()
            raise
        except sqlite3.DatabaseError as exc:
            logger.error(f"Pool store damaged, recovering: {exc}")
            self._connections.close()
            self._recover_corrupt_file()
            self._connections = ThreadConnections()
            conn = self._thread_conn()
            conn.executescript(_SCHEMA + telegram_tracking.SCHEMA)
            self.set_meta("schema_version", str(SCHEMA_VERSION))

        # Older trackers rejected the entire minute for any multi-price timestamp.
        # Change the old reason atomically so a restart never replenishes retries.
        with self._transaction() as conn:
            conn.execute("""
                UPDATE chat_plans SET state='UNVERIFIED', payload=json_set(
                    json_remove(payload, '$.manual_review', '$.retry_at'), '$.status', 'UNVERIFIED',
                    '$.resolved_at', COALESCE(json_extract(payload, '$.history_checked_at'), ?))
                WHERE state='AMBIGUOUS' AND (json_extract(payload, '$.retry_count') >= ?
                    OR json_extract(payload, '$.manual_review')=1)
            """, (int(time.time()*1000), telegram_tracking.MAX_VERIFICATION_ATTEMPTS))
            conn.execute("""
                UPDATE chat_plans SET payload = json_set(
                    json_remove(payload, '$.manual_review', '$.retry_at'),
                    '$.ambiguity_reason', 'Geçmiş işlemler yeniden doğrulanacak')
                WHERE state='AMBIGUOUS' AND json_extract(payload, '$.ambiguity_reason')=?
            """, ("Aynı milisaniyede farklı işlem fiyatları",))

            # Older releases could archive an open remainder solely on a transport
            # timeout. Resume only the current followed revision with confirmed TPs.
            conn.execute("""
                UPDATE chat_plans AS p SET state='AMBIGUOUS', payload=json_set(
                    json_remove(payload,'$.retry_count','$.retry_at','$.resolved_at','$.manual_review'),
                    '$.status','PENDING', '$.ambiguity_reason','Bağlantı sonrası geçmiş kontrolü bekleniyor')
                WHERE state='UNVERIFIED' AND json_array_length(payload,'$.tps_hit') BETWEEN 1 AND 2
                  AND json_extract(payload,'$.ambiguity_reason') IN (
                    'Gate.io geçmiş verisi alınamadı (TimeoutError)', 'Gate.io geçmiş verisi alınamadı (ReadTimeout)',
                    'Gate.io geçmiş verisi alınamadı (ConnectTimeout)', 'Gate.io geçmiş verisi alınamadı (ConnectionError)',
                    'Gate.io geçmiş verisi alınamadı (Timeout)')
                  AND EXISTS (SELECT 1 FROM chat_follows f WHERE f.chat=p.chat AND f.symbol=p.symbol
                              AND f.revision=p.revision)
                  AND NOT EXISTS (SELECT 1 FROM chat_tracking_preferences f WHERE f.chat=p.chat AND f.symbol=p.symbol
                                  AND (f.muted=1 OR f.changed_at >= json_extract(p.payload,'$.resolved_at')))
            """)

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
                    raise

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

    def save_snapshot(self, candidates, validated, active, history, *, publication=None):
        """Commit a lifecycle transition and its history as one durable unit."""
        with self._transaction() as conn:
            if publication:
                key, incoming, _ = publication
                previous = conn.execute("SELECT value FROM pool_meta WHERE key=?", (key,)).fetchone()
                if previous:
                    elapsed = incoming - int(previous[0])
                    if elapsed <= 0 or (key == "pool_cleanup_ms" and elapsed < 86400000):
                        raise RuntimeError("Pool publication overtaken by another writer")
            for name, records in (("candidates", candidates), ("validated", validated), ("active", active)):
                self.save_pool(name, records, connection=conn)
            self.append_history(history, connection=conn)
            if publication:
                marker, value, decisions = publication
                conn.execute("INSERT OR REPLACE INTO pool_meta VALUES(?,?)", (marker,str(value)))
                for row in decisions:
                    symbol = row["symbol"]
                    if row.get("version"):
                        conn.execute("INSERT OR REPLACE INTO pool_meta VALUES(?,?)", ("version:"+symbol,str(row["version"])))
                    conn.execute("INSERT OR REPLACE INTO pool_meta VALUES(?,?)",
                                 ("cycle:"+symbol,json.dumps([row["cutoff"],row["observed"]])))
                    # Save material changes even when nobody currently follows the symbol.
                    # An HTTP reply can be in flight across several publications.
                    keys = ["broken:"+symbol+":"+sid for sid in row.get("broken", [])]
                    if row.get("setup"):
                        keys.append("selected:"+symbol)
                    conn.executemany("INSERT OR REPLACE INTO pool_meta VALUES(?,?)",
                                     [(key,json.dumps(row)) for key in keys])
                    followers = conn.execute("SELECT chat,revision FROM chat_follows WHERE symbol=?", (symbol,)).fetchall()
                    for chat,revision in followers:
                        self._apply_observation(conn, chat, revision, row, announce=True)

    def _apply_observation(self, conn, chat, revision, row, *, announce):
        symbol = row["symbol"]
        preference = conn.execute("SELECT muted,changed_at FROM chat_tracking_preferences WHERE chat=? AND symbol=?",
                                  (chat, symbol)).fetchone()
        if preference and (preference[0] or row["observed"] <= preference[1]):
            return
        stamp = (row["cutoff"], row["observed"])
        key = f"watch:{chat}:{symbol}"
        old = conn.execute("SELECT value FROM pool_meta WHERE key=?", (key,)).fetchone()
        if old and stamp < tuple(json.loads(old[0])):
            return
        conn.execute("INSERT OR REPLACE INTO pool_meta VALUES(?,?)", (key,json.dumps(stamp)))
        setup = row.get("setup")
        if not setup:
            plan = conn.execute("SELECT payload FROM chat_plans WHERE chat=? AND symbol=? AND revision=?",
                                (chat,symbol,revision)).fetchone()
            if not plan or json.loads(plan[0]).get("strategy_id") not in row["broken"]:
                return
        telegram_tracking.transition(conn, chat, symbol, revision, setup, announce=announce)

    def follow_analysis(self, chat, row):
        self.follow_delivered(chat, [row])

    def follow_delivered(self, chat, observations):
        with self._transaction() as conn:
            for row in observations:
                symbol = row["symbol"]
                if row.get("setup"):
                    conn.execute("INSERT OR IGNORE INTO chat_follows(chat,symbol) VALUES(?,?)", (chat,symbol))
                member = conn.execute("SELECT revision FROM chat_follows WHERE chat=? AND symbol=?",
                                      (chat,symbol)).fetchone()
                if not member:
                    continue
                self._apply_observation(conn, chat, member[0], row, announce=member[0]>0)
                if not row.get("setup"):
                    continue
                changes = []
                strategies = {row["setup"]["strategy_id"]}
                selected = self.get_meta("selected:"+symbol)
                if selected:
                    latest = json.loads(selected)
                    changes.append(latest)
                    strategies.add(latest["setup"]["strategy_id"])
                for sid in strategies:
                    broken = self.get_meta("broken:"+symbol+":"+sid)
                    if broken:
                        changes.append(json.loads(broken))
                for newer in sorted(changes, key=lambda item: (item["cutoff"],item["observed"])):
                    if (newer["cutoff"],newer["observed"]) <= (row["cutoff"],row["observed"]):
                        continue
                    revision, = conn.execute("SELECT revision FROM chat_follows WHERE chat=? AND symbol=?",
                                             (chat,symbol)).fetchone()
                    self._apply_observation(conn, chat, revision, newer, announce=True)

    def displayed_observations(self, setups):
        observations = []
        for setup in setups:
            cutoff, observed = json.loads(self.get_meta("cycle:"+setup.symbol, "[0,0]"))
            observations.append(dict(symbol=setup.symbol, cutoff=cutoff, observed=observed,
                                     setup=setup.to_dict(), broken=[]))
        return observations

    def follow(self, chat, setups):
        self.follow_delivered(chat,self.displayed_observations(setups))

    def set_symbol_tracking(self, chat, symbol, *, enabled):
        """Change this chat's subscription and retire its open plans atomically."""
        now = int(time.time() * 1000)
        with self._transaction() as conn:
            follows = conn.execute("SELECT 1 FROM chat_follows WHERE chat=? AND symbol=?", (chat, symbol)).fetchone()
            pref = conn.execute("SELECT muted FROM chat_tracking_preferences WHERE chat=? AND symbol=?",
                                (chat, symbol)).fetchone()
            if enabled:
                if follows and not (pref and pref[0]):
                    return False
                conn.execute("INSERT OR IGNORE INTO chat_follows(chat,symbol) VALUES(?,?)", (chat, symbol))
                conn.execute("INSERT INTO chat_tracking_preferences VALUES(?,?,0,?,0) "
                             "ON CONFLICT(chat,symbol) DO UPDATE SET muted=0,changed_at=excluded.changed_at",
                             (chat, symbol, now))
            else:
                if not follows or (pref and pref[0]):
                    return False
                conn.execute("INSERT OR REPLACE INTO chat_tracking_preferences "
                             "SELECT ?,?,1,?,COALESCE(MAX(id),0) FROM chat_events WHERE chat=? AND symbol=?",
                             (chat, symbol, now, chat, symbol))
                conn.execute("UPDATE chat_plans SET state='REMOVED',payload=json_set(payload,'$.status','REMOVED','$.resolved_at',?) "
                             "WHERE chat=? AND symbol=? AND state IN ('WAITING','ACTIVE','AMBIGUOUS')",
                             (now, chat, symbol))
            return True

    def tracked(self, chat):
        return list(self.iter_tracked(chat))

    def iter_tracked(self, chat):
        for symbol, revision, state, payload, muted in self._thread_conn().execute(
                "SELECT p.symbol,p.revision,p.state,p.payload,f.muted FROM chat_plans p "
                "LEFT JOIN chat_tracking_preferences f USING(chat,symbol) WHERE p.chat=? "
                "ORDER BY p.symbol,p.revision DESC", (chat,)):
            plan = json.loads(payload)
            if muted:
                plan["tracking_muted"] = True
            yield symbol, revision, state, plan

    def open_symbols(self, *, due_only=False):
        now = int(time.time() * 1000)
        # Legacy rows without an explicit next bar still go through the normal evaluator.
        due = " AND COALESCE(json_extract(payload,'$.next_bar_time'),0)<=?" if due_only else ""
        params = (now, now - telegram_tracking.BAR) if due_only else (now,)
        return [row[0] for row in self._thread_conn().execute(
            "SELECT symbol FROM chat_plans WHERE state IN ('WAITING','ACTIVE','AMBIGUOUS') "
            "AND COALESCE(json_extract(payload,'$.manual_review'),0)=0 "
            "AND COALESCE(json_extract(payload,'$.retry_at'),0)<=?" + due +
            " GROUP BY symbol ORDER BY MIN(CASE WHEN state='ACTIVE' OR json_extract(payload,'$.entry_reached')=1 "
            "THEN 0 WHEN state='AMBIGUOUS' THEN 1 ELSE 2 END),symbol", params)]

    def advance_tracking(self, symbol, candles=None, *, history=None):
        now = int(time.time() * 1000)
        rows = self._thread_conn().execute(
            "SELECT chat,revision,state,payload FROM chat_plans WHERE symbol=? "
            "AND state IN ('ACTIVE','WAITING','AMBIGUOUS')", (symbol,)).fetchall()
        for row in rows:
            if row[2] == "AMBIGUOUS" and history is None:
                continue
            result = telegram_tracking.evaluate(symbol, row[2], row[3], now, candles, history)
            if result:
                # Network and replay run outside the writer lock. CAS rejects stale snapshots.
                with self._transaction() as conn:
                    telegram_tracking.save(conn, symbol, row, result)

    def pending_notifications(self, chat):
        return self._thread_conn().execute(
            "SELECT e.id,e.message FROM chat_events e LEFT JOIN chat_tracking_preferences p USING(chat,symbol) "
            "WHERE e.chat=? AND e.delivered=0 AND e.id>COALESCE(p.suppress_through,0) ORDER BY e.id LIMIT 50", (chat,)
        ).fetchall()

    def claim_notification(self, chat):
        """Commit the send intent before crossing the non-idempotent HTTP boundary."""
        now = int(time.time())
        with self._transaction() as conn:
            conn.execute("UPDATE chat_event_delivery SET state='uncertain' WHERE state='sending' AND next_at<=?",
                         (now,))
            row = conn.execute("""
                SELECT e.id,e.message,d.state,d.attempts,d.next_at
                FROM chat_events e LEFT JOIN chat_event_delivery d ON e.id=d.event_id
                LEFT JOIN chat_tracking_preferences p ON p.chat=e.chat AND p.symbol=e.symbol
                WHERE e.chat=? AND e.delivered=0 AND e.id>COALESCE(p.suppress_through,0) AND (d.state IS NULL OR d.state IN ('sending','retry'))
                ORDER BY e.id LIMIT 1
            """, (chat,)).fetchone()
            if not row:
                return None
            event_id, message, state, attempts, next_at = row
            if state == "sending" or (next_at and next_at > now):
                return None
            attempt = (attempts or 0) + 1
            conn.execute("INSERT OR REPLACE INTO chat_event_delivery VALUES(?, 'sending', ?, ?, NULL)",
                         (event_id, attempt, now + 120))
            return event_id, message, attempt

    def finish_notification(self, chat, event_id, attempt, state, *, message_id=None, retry_after=0):
        now = int(time.time())
        with self._transaction() as conn:
            changed = conn.execute("""
                UPDATE chat_event_delivery SET state=?, next_at=?, message_id=?
                WHERE event_id=? AND attempts=? AND state IN ('sending','uncertain')
                  AND EXISTS (SELECT 1 FROM chat_events WHERE id=? AND chat=?)
            """, (state, now + retry_after, message_id, event_id, attempt, event_id, chat)).rowcount
            if changed and state == "sent":
                conn.execute("UPDATE chat_events SET delivered=1 WHERE id=? AND chat=?", (event_id, chat))

    def unconfirmed_notifications(self, chat):
        return self._thread_conn().execute("""
            SELECT COUNT(*) FROM chat_event_delivery d JOIN chat_events e ON e.id=d.event_id
            WHERE e.chat=? AND d.state IN ('uncertain','failed')
        """, (chat,)).fetchone()[0]

    def save_pool(self, pool: str, records: Dict[str, Dict[str, Any]], *, connection=None) -> int:
        """Replace the stored contents of one live pool in a single transaction.

        Records present in `records` are upserted; stored ids that are absent
        were removed in memory and are deleted here, so the DB always mirrors
        the current in-memory pool exactly.
        """
        now_ms = int(time.time() * 1000)
        with (nullcontext(connection) if connection is not None else self._transaction()) as conn:
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

    def append_history(self, records: List[Dict[str, Any]], *, connection=None) -> int:
        """Append archived setups. Idempotent via the natural unique key."""
        if not records:
            return 0
        inserted = 0
        with (nullcontext(connection) if connection is not None else self._transaction()) as conn:
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
        # Walk newest first and stop after the requested number of valid rows.
        rows = self._thread_conn().execute("SELECT payload FROM history ORDER BY archive_id DESC")
        result = []
        for (payload,) in rows:
            try:
                result.append(json.loads(payload))
            except (TypeError, ValueError):
                continue
            if limit and limit > 0 and len(result) >= limit:
                break
        result.reverse()
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


    def close(self):
        self._connections.close()


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
