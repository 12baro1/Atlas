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
