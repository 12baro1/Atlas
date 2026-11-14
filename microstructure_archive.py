"""Local JSONL archive for timestamped live microstructure snapshots.

This creates a future replay dataset; it does not backfill historical order books.
"""
from __future__ import annotations

import json
import os
import threading
import time
from bisect import bisect_right

_LOCK = threading.RLock()
_CACHE = {}


def _path(symbol):
    safe = str(symbol).replace("/", "_").replace(":", "_").replace("\\", "_")
    root = os.getenv("ATLAS_MICROSTRUCTURE_ARCHIVE_DIR", "data/microstructure")
    return os.path.join(root, safe + ".jsonl")


def _prune_if_needed(path, now_ms):
    try:
        max_bytes = int(os.getenv("ATLAS_MICROSTRUCTURE_ARCHIVE_MAX_BYTES", str(5 * 1024 * 1024)))
        retention_days = int(os.getenv("ATLAS_MICROSTRUCTURE_ARCHIVE_RETENTION_DAYS", "7"))
    except (TypeError, ValueError):
        max_bytes, retention_days = 5 * 1024 * 1024, 7
    max_bytes = max(1024, max_bytes)
    retention_ms = max(1, retention_days) * 24 * 60 * 60 * 1000
    cutoff_ms = int(now_ms) - retention_ms
    try:
        size = os.path.getsize(path)
        if size <= max_bytes:
            with open(path, "r", encoding="utf-8") as handle:
                first_line = handle.readline()
            try:
                oldest_ms = int(json.loads(first_line).get("snapshot_timestamp_ms") or 0)
            except (ValueError, TypeError):
                oldest_ms = 0
            if oldest_ms >= cutoff_ms:
                return False
        rows = []
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                    stamp = int(row.get("snapshot_timestamp_ms") or 0)
                except (ValueError, TypeError):
                    continue
                if stamp >= cutoff_ms:
                    rows.append((stamp, line if line.endswith("\n") else line + "\n"))
        rows.sort(key=lambda item: item[0])
        while len(rows) > 1 and sum(len(line.encode("utf-8")) for _, line in rows) > max_bytes:
            rows.pop(0)
        if not rows:
            return False
        temp_path = path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            for _, line in rows:
                handle.write(line)
        os.replace(temp_path, path)
        _CACHE.pop(path, None)
        return True
    except OSError:
        return False


def record_snapshot(symbol, data):
    book = data.get("orderbook")
    trades = data.get("recent_trades")
    if not isinstance(book, dict) and not isinstance(trades, list):
        return False
    timestamp = int(data.get("snapshot_timestamp_ms") or 0)
    if timestamp <= 0:
        return False
    row = {
        "symbol": str(symbol),
        "snapshot_timestamp_ms": timestamp,
        "orderbook_timestamp_ms": data.get("orderbook_timestamp_ms"),
        "recent_trades_timestamp_ms": data.get("recent_trades_timestamp_ms"),
        "orderbook": book if isinstance(book, dict) else None,
        "recent_trades": trades if isinstance(trades, list) else None,
    }
    path = _path(symbol)
    with _LOCK:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        # Avoid duplicate writes when the same immutable snapshot is reused.
        try:
            with open(path, "rb") as handle:
                handle.seek(max(0, os.path.getsize(path) - 8192))
                tail = handle.read().decode("utf-8", errors="ignore").splitlines()
            if tail:
                previous = json.loads(tail[-1])
                if int(previous.get("snapshot_timestamp_ms") or 0) == timestamp:
                    return False
        except (OSError, ValueError, TypeError):
            pass
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")
            handle.flush()
        _prune_if_needed(path, timestamp or int(time.time() * 1000))
    return True


def snapshot_at(symbol, asof_ms, *, book_max_age_ms=15_000, trades_max_age_ms=30_000):
    """Return the newest archived feed snapshot available at or before asof_ms."""
    path = _path(symbol)
    try:
        stat = os.stat(path)
        cache_key = (stat.st_mtime_ns, stat.st_size)
        cached = _CACHE.get(path)
        if cached is None or cached[0] != cache_key:
            rows = []
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        row = json.loads(line)
                        stamp = int(row.get("snapshot_timestamp_ms") or 0)
                    except (ValueError, TypeError):
                        continue
                    if stamp > 0:
                        rows.append((stamp, row))
            rows.sort(key=lambda item: item[0])
            cached = (cache_key, rows, [item[0] for item in rows])
            _CACHE[path] = cached
        rows, stamps = cached[1], cached[2]
    except OSError:
        return None
    index = bisect_right(stamps, int(asof_ms)) - 1
    if index < 0:
        return None
    best = rows[index]
    row = best[1]
    book_ms = int(row.get("orderbook_timestamp_ms") or 0)
    trades_ms = int(row.get("recent_trades_timestamp_ms") or 0)
    return {
        "orderbook": row.get("orderbook") if 0 <= asof_ms - book_ms <= book_max_age_ms else None,
        "orderbook_timestamp_ms": book_ms or None,
        "recent_trades": row.get("recent_trades") if 0 <= asof_ms - trades_ms <= trades_max_age_ms else None,
        "recent_trades_timestamp_ms": trades_ms or None,
        "microstructure_snapshot_timestamp_ms": best[0],
    }
