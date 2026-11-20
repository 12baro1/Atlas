import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from pool_store import PoolStore
from scan_queue import ScanQueue


@pytest.mark.parametrize("store_type", [PoolStore, ScanQueue])
def test_short_lived_workers_release_databases_and_preserve_live_owner(store_type, tmp_path):
    store = store_type(tmp_path)
    main = store._thread_conn()
    try:
        with ThreadPoolExecutor(1) as live:
            persistent = live.submit(store._thread_conn).result()
            for _ in range(10):
                with ThreadPoolExecutor(1) as short:
                    ended = short.submit(store._thread_conn).result()
                with ThreadPoolExecutor(1) as replacement:
                    replacement.submit(store._thread_conn).result()
                with pytest.raises(sqlite3.ProgrammingError):
                    ended.execute("SELECT 1")
            assert live.submit(store._thread_conn).result() is persistent
            assert persistent.execute("SELECT 1").fetchone() == (1,)
            assert main.execute("SELECT 1").fetchone() == (1,)
    finally:
        store.close()
    with pytest.raises(sqlite3.ProgrammingError):
        store._thread_conn()
