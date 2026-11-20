"""Tests for the SQLite pool store: transactions, WAL, migration, backup, recovery."""
import json
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pool_store import PoolStore


def sample_payload(setup_id="s1", symbol="BTC/USDT:USDT", strategy="smc", status="DISCOVERED"):
    return {
        "setup_id": setup_id,
        "symbol": symbol,
        "strategy_id": strategy,
        "strategy_name": strategy,
        "direction": "LONG",
        "status": status,
        "entry_price": 50000.0,
        "stop_loss": 49500.0,
        "created_at_ms": 1700000000000,
        "updated_at_ms": 1700000000000,
    }


def history_payload(setup_id="s1", status="EXPIRED", closed_at=1700000000000):
    return {
        "setup_id": setup_id,
        "status": status,
        "closed_at_ms": closed_at,
        "invalidation_reason": "Expired",
    }


def test_wal_mode_active(tmp_path):
    store = PoolStore(str(tmp_path))
    try:
        mode = store._thread_conn().execute("PRAGMA journal_mode").fetchone()[0]
        assert str(mode).lower() == "wal"
    finally:
        store.close()


def test_save_and_load_roundtrip(tmp_path):
    store = PoolStore(str(tmp_path))
    try:
        store.save_pool("candidates", {"s1": sample_payload()})
        loaded = store.load_pool("candidates")
        assert loaded["s1"]["entry_price"] == 50000.0
    finally:
        store.close()


def test_save_pool_removes_deleted_ids(tmp_path):
    store = PoolStore(str(tmp_path))
    try:
        store.save_pool("candidates", {"s1": sample_payload(), "s2": sample_payload("s2")})
        store.save_pool("candidates", {"s1": sample_payload()})
        loaded = store.load_pool("candidates")
        assert set(loaded) == {"s1"}
    finally:
        store.close()


def test_transaction_rollback_on_error(tmp_path):
    store = PoolStore(str(tmp_path))
    try:
        store.save_pool("candidates", {"s1": sample_payload()})
        with pytest.raises(ValueError):
            with store._transaction() as conn:
                conn.execute(
                    "INSERT INTO setups(setup_id, pool, symbol, strategy_id, direction, "
                    "status, payload) VALUES('s2', 'candidates', 'X', 'Y', 'LONG', 'S', '{}')"
                )
                raise ValueError("boom")
        loaded = store.load_pool("candidates")
        assert set(loaded) == {"s1"}, "failed transaction must roll back"
    finally:
        store.close()


def test_history_idempotent_appends(tmp_path):
    store = PoolStore(str(tmp_path))
    try:
        row = history_payload()
        assert store.append_history([row]) == 1
        assert store.append_history([row]) == 0  # same natural key ignored
        assert len(store.load_history()) == 1
        # Same setup closed again at another time is a distinct archive row
        assert store.append_history([history_payload(closed_at=1700000001000)]) == 1
        assert len(store.load_history()) == 2
    finally:
        store.close()


def test_json_migration_idempotent(tmp_path):
    # Legacy layout
    (tmp_path / "candidates.json").write_text(json.dumps({
        "candidates": {"s1": sample_payload(), "s2": sample_payload("s2", "ETH/USDT:USDT")}
    }))
    (tmp_path / "history.json").write_text(json.dumps({"history": [history_payload()]}))

    store = PoolStore(str(tmp_path))
    try:
        first = store.migrate_from_json(tmp_path)
        assert first["candidates"] == 2
        assert first["history"] == 1
        second = store.migrate_from_json(tmp_path)
        assert second["candidates"] == 0, "re-running migration must not duplicate"
        assert second["history"] == 0
        assert len(store.load_pool("candidates")) == 2
        assert len(store.load_history()) == 1
    finally:
        store.close()


def test_backup_contains_state(tmp_path):
    store = PoolStore(str(tmp_path))
    try:
        store.save_pool("validated", {"s1": sample_payload(status="VALIDATED")})
        backup_path = store.backup(tmp_path / "backup" / "pool_state.db")
        restored = PoolStore(str(tmp_path / "backup"))
        try:
            loaded = restored.load_pool("validated")
            assert loaded["s1"]["setup_id"] == "s1"
        finally:
            restored.close()
        assert os.path.exists(backup_path)
    finally:
        store.close()


def test_corrupt_store_quarantined_and_recreated(tmp_path):
    store = PoolStore(str(tmp_path))
    store.save_pool("candidates", {"s1": sample_payload()})
    store.close()
    (tmp_path / "pool_state.db").write_bytes(b"garbage" * 100)
    reconnected = PoolStore(str(tmp_path))
    try:
        assert reconnected.load_pool("candidates") == {}
        quarantined = list(tmp_path.glob("pool_state.corrupt-*"))
        assert quarantined
        assert reconnected.get_meta("schema_version") is not None
    finally:
        reconnected.close()


def test_concurrent_writers_safe(tmp_path):
    store = PoolStore(str(tmp_path))
    try:
        errors = []

        def worker(worker_id):
            try:
                for index in range(20):
                    sid = f"w{worker_id}-{index}"
                    store.save_pool("candidates", {sid: sample_payload(sid)})
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        assert not errors
        # Each worker saved its own single-record snapshot; last writer per id
        # semantics must hold and the DB must remain readable.
        loaded = store.load_pool("candidates")
        assert isinstance(loaded, dict)
    finally:
        store.close()


def test_meta_roundtrip(tmp_path):
    store = PoolStore(str(tmp_path))
    try:
        assert store.get_meta("missing") is None
        store.set_meta("last_refresh_day", "2026-11-17")
        assert store.get_meta("last_refresh_day") == "2026-11-17"
        store.set_meta("last_refresh_day", "2026-11-18")
        assert store.get_meta("last_refresh_day") == "2026-11-18"
    finally:
        store.close()


def test_snapshot_failure_rolls_back_all_pools_and_history(tmp_path):
    import pytest
    store = PoolStore(str(tmp_path))
    original = {"s1": sample_payload()}
    store.save_snapshot(original, {}, {}, [])
    with pytest.raises(TypeError):
        store.save_snapshot({}, {}, original, [{"invalid_json": object()}])
    assert store.load_pool("candidates") == original
    assert store.load_pool("active") == {}
    assert store.load_history() == []
    store.close()


def test_history_limit_only_decodes_recent_rows(tmp_path, monkeypatch):
    store = PoolStore(str(tmp_path))
    try:
        store.append_history([history_payload(str(i)) for i in range(100)])
        decoded = []
        load = json.loads

        def count(payload):
            decoded.append(payload)
            return load(payload)

        monkeypatch.setattr(json, "loads", count)
        assert [row["setup_id"] for row in store.load_history(3)] == ["97", "98", "99"]
        assert len(decoded) == 3
    finally:
        store.close()
