import json

from microstructure_archive import record_snapshot, snapshot_at


def test_archive_round_trip_and_no_lookahead(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_MICROSTRUCTURE_ARCHIVE_DIR", str(tmp_path))
    symbol = "BTC/USDT:USDT"
    row = {
        "snapshot_timestamp_ms": 1_700_000_000_000,
        "orderbook_timestamp_ms": 1_700_000_000_000,
        "recent_trades_timestamp_ms": 1_700_000_000_000,
        "orderbook": {"bids": [[100, 2]], "asks": [[101, 3]]},
        "recent_trades": [{"timestamp": 1_700_000_000_000, "side": "buy", "amount": 1}],
    }
    assert record_snapshot(symbol, row) is True
    assert record_snapshot(symbol, row) is False
    assert snapshot_at(symbol, 1_699_999_999_999) is None
    restored = snapshot_at(symbol, 1_700_000_000_000)
    assert restored["orderbook"] == row["orderbook"]
    assert restored["recent_trades"] == row["recent_trades"]


def test_stale_archived_feeds_are_not_replayed(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_MICROSTRUCTURE_ARCHIVE_DIR", str(tmp_path))
    symbol = "ETH/USDT:USDT"
    row = {
        "snapshot_timestamp_ms": 1_700_000_000_000,
        "orderbook_timestamp_ms": 1_700_000_000_000,
        "recent_trades_timestamp_ms": 1_700_000_000_000,
        "orderbook": {"bids": [[100, 2]], "asks": [[101, 3]]},
        "recent_trades": [],
    }
    record_snapshot(symbol, row)
    restored = snapshot_at(symbol, 1_700_000_100_000)
    assert restored["orderbook"] is None
    assert restored["recent_trades"] is None


def test_archive_prunes_old_rows_to_configured_size_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_MICROSTRUCTURE_ARCHIVE_DIR", str(tmp_path))
    monkeypatch.setenv("ATLAS_MICROSTRUCTURE_ARCHIVE_MAX_BYTES", "1024")
    monkeypatch.setenv("ATLAS_MICROSTRUCTURE_ARCHIVE_RETENTION_DAYS", "7")
    symbol = "SOL/USDT:USDT"
    start = 1_800_000_000_000
    for index in range(20):
        stamp = start + index * 1000
        record_snapshot(symbol, {
            "snapshot_timestamp_ms": stamp,
            "orderbook_timestamp_ms": stamp,
            "recent_trades_timestamp_ms": stamp,
            "orderbook": {"bids": [[100, 1]], "asks": [[101, 1]]},
            "recent_trades": [{"timestamp": stamp, "side": "buy", "amount": 1}],
        })
    archive_path = tmp_path / "SOL_USDT_USDT.jsonl"
    assert archive_path.stat().st_size <= 1024
    rows = [json.loads(line) for line in archive_path.read_text().splitlines()]
    assert 0 < len(rows) < 20
    latest = snapshot_at(symbol, start + 19_000)
    assert latest["orderbook"] == {"bids": [[100, 1]], "asks": [[101, 1]]}
