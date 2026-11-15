"""WebSocket ilk snapshot testleri: sınırlı bekleme, sonsuz bekleme yok,
kaynak etiketi yalnızca gerçekten kullanılan taze veri için."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from strategies.orderflow.websocket_collector import (
    BybitPublicStream,
    DEFAULT_FIRST_SNAPSHOT_WAIT_MS,
    MAX_FIRST_SNAPSHOT_WAIT_MS,
    configured_first_snapshot_wait_ms,
)


SYMBOL = "TESTUSDT/USDT:USDT"


@pytest.fixture
def stream():
    # Bağlantı kurulmaz: yalnızca sınıf içi durum test edilir (offline test).
    instance = BybitPublicStream(SYMBOL)
    yield instance
    instance.stop()


def inject_fresh_book(stream, now_ms):
    stream._consume({
        "topic": f"orderbook.50.{stream.instrument}",
        "type": "snapshot",
        "ts": now_ms,
        "data": {"b": [["100", "10"]], "a": [["101", "10"]]},
    })


def inject_fresh_trades(stream, now_ms):
    stream._consume({
        "topic": f"publicTrade.{stream.instrument}",
        "ts": now_ms,
        "data": [{"T": now_ms, "p": "100.5", "v": "1.5", "S": "Buy", "i": "t1"}],
    })


def test_configured_first_snapshot_wait_ms_defaults_to_2500(monkeypatch):
    monkeypatch.delenv("ATLAS_WS_FIRST_SNAPSHOT_TIMEOUT_MS", raising=False)
    assert configured_first_snapshot_wait_ms() == 2500.0


def test_configured_wait_is_capped_and_never_infinite(monkeypatch):
    monkeypatch.setenv("ATLAS_WS_FIRST_SNAPSHOT_TIMEOUT_MS", "999999")
    assert configured_first_snapshot_wait_ms() == MAX_FIRST_SNAPSHOT_WAIT_MS
    assert MAX_FIRST_SNAPSHOT_WAIT_MS == 15000.0
    assert DEFAULT_FIRST_SNAPSHOT_WAIT_MS == 2500.0


def test_zero_config_disables_the_wait(monkeypatch):
    monkeypatch.setenv("ATLAS_WS_FIRST_SNAPSHOT_TIMEOUT_MS", "0")
    assert configured_first_snapshot_wait_ms() == 0.0


def test_invalid_config_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("ATLAS_WS_FIRST_SNAPSHOT_TIMEOUT_MS", "not-a-number")
    assert configured_first_snapshot_wait_ms() == DEFAULT_FIRST_SNAPSHOT_WAIT_MS


def test_await_first_message_returns_after_deadline_when_silent(stream):
    start = time.monotonic()
    got_message = stream._await_first_message(0.25)
    elapsed = time.monotonic() - start

    assert got_message is False
    # Sınırlı: 0.25 sn'lik deadline sonrası döner; sonsuz bloke yok.
    assert 0.2 <= elapsed < 2.0


def test_await_first_message_returns_immediately_on_message(stream):
    inject_fresh_book(stream, int(time.time() * 1000))

    start = time.monotonic()
    got_message = stream._await_first_message(5.0)
    elapsed = time.monotonic() - start

    assert got_message is True
    assert elapsed < 1.0


def test_snapshot_with_zero_wait_does_not_block_on_silent_stream(stream):
    start = time.monotonic()
    snapshot = stream.snapshot(int(time.time() * 1000), wait_ms=0)
    elapsed = time.monotonic() - start

    assert elapsed < 0.5
    assert snapshot["orderbook"] is None
    assert snapshot["orderbook_source"] == "UNAVAILABLE"
    assert snapshot["recent_trades"] == []
    assert snapshot["recent_trades_source"] == "UNAVAILABLE"
    assert snapshot["liquidation_events_source"] == "UNAVAILABLE"
    assert snapshot["trade_flow_history_source"] == "UNAVAILABLE"


def test_snapshot_waits_at_most_the_configured_wait_then_falls_back(stream):
    start = time.monotonic()
    snapshot = stream.snapshot(int(time.time() * 1000), wait_ms=300)
    elapsed = time.monotonic() - start

    assert elapsed < 2.0
    assert snapshot["last_message_timestamp_ms"] is None
    assert snapshot["orderbook_source"] == "UNAVAILABLE"


def test_snapshot_labels_sources_only_for_actually_used_fresh_data(stream):
    now_ms = int(time.time() * 1000)
    inject_fresh_book(stream, now_ms)
    inject_fresh_trades(stream, now_ms)
    stream._consume({
        "topic": f"allLiquidation.{stream.instrument}",
        "ts": now_ms,
        "data": {"T": now_ms, "p": "100", "v": "5", "S": "Sell"},
    })

    snapshot = stream.snapshot(now_ms + 10, wait_ms=0)

    assert snapshot["orderbook_source"] == "WEBSOCKET"
    assert snapshot["recent_trades_source"] == "WEBSOCKET"
    assert snapshot["liquidation_events_source"] == "WEBSOCKET"
    assert snapshot["trade_flow_history_source"] == "WEBSOCKET"
    assert snapshot["trade_flow_history"]  # timestamped batches exist


def test_stale_book_is_not_labeled_websocket(stream):
    stale_ms = int(time.time() * 1000) - 60_000
    inject_fresh_book(stream, stale_ms)

    snapshot = stream.snapshot(int(time.time() * 1000), wait_ms=0)

    assert snapshot["orderbook"] is None
    assert snapshot["orderbook_source"] == "UNAVAILABLE"
