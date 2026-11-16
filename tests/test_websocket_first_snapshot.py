"""Gate.io public stream snapshot behavior tests (offline; no network connection)."""
from strategies.orderflow.gateio_public_stream import GatePublicStream


def test_snapshot_is_nonblocking_when_stream_has_no_messages():
    stream = GatePublicStream("BTC/USDT:USDT")
    snapshot = stream.snapshot(wait_ms=0)
    assert snapshot["recent_trades"] == []
    assert snapshot["recent_trades_source"] == "UNAVAILABLE"
    assert snapshot["liquidation_events"] == []
    assert snapshot["liquidation_events_source"] == "UNAVAILABLE"


def test_subscribe_ack_does_not_count_as_market_data_or_liquidation():
    stream = GatePublicStream("BTC/USDT:USDT")
    stream._consume({
        "channel": "futures.public_liquidates",
        "event": "subscribe",
        "result": {"status": "success"},
    })
    snapshot = stream.snapshot()
    assert snapshot["liquidation_events"] == []
    assert snapshot["recent_trades"] == []
    assert snapshot["recent_trades_source"] == "UNAVAILABLE"


def test_fresh_trade_update_is_exposed_with_gate_source():
    stream = GatePublicStream("BTC/USDT:USDT")
    now_ms = 1700000001000
    stream._consume({
        "channel": "futures.trades",
        "event": "update",
        "time_ms": now_ms,
        "result": [{
            "id": 123, "create_time_ms": now_ms,
            "price": "60000", "size": "2",
        }],
    })
    snapshot = stream.snapshot(now_ms=now_ms, wait_ms=0)
    assert snapshot["recent_trades"]
    assert snapshot["recent_trades"][0]["side"] == "BUY"
    assert snapshot["recent_trades_source"] == "WEBSOCKET"
    assert snapshot["trade_flow_history_source"] == "WEBSOCKET"
