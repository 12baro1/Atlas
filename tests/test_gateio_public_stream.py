from strategies.orderflow.gateio_public_stream import GatePublicStream


def test_public_liquidation_events_are_normalized_and_deduplicated():
    stream = GatePublicStream("BTC/USDT:USDT")
    message = {
        "channel": "futures.public_liquidates",
        "event": "update",
        "time_ms": 1700000001000,
        "result": [
            {"contract": "BTC_USDT", "price": "60000", "size": "-0.2", "time": 1700000000000},
            {"contract": "ETH_USDT", "price": "3000", "size": "1", "time": 1700000000000},
        ],
    }
    stream._consume(message)
    stream._consume(message)
    snapshot = stream.snapshot(now_ms=1700000001000)
    assert len(snapshot["liquidation_events"]) == 1
    event = snapshot["liquidation_events"][0]
    assert event["exchange"] == "GATEIO_FUTURES"
    assert event["symbol"] == "BTC"
    assert event["side"] == "SELL"
    assert event["order_side"] == "SELL"
    assert event["side_semantics"] == "GATE_LIQUIDATION_ORDER_SIDE"
    assert event["notional"] == 12000
    assert event["source"] == "GATEIO_FUTURES_PUBLIC_LIQUIDATES_WS"


def test_subscribe_ack_is_not_misreported_as_liquidation_event():
    stream = GatePublicStream("BTC/USDT:USDT")
    stream._consume({
        "channel": "futures.public_liquidates", "event": "subscribe",
        "result": {"status": "success"},
    })
    snapshot = stream.snapshot()
    assert snapshot["liquidation_events"] == []


def test_future_and_nonfinite_trades_do_not_enter_cvd():
    stream = GatePublicStream("BTC/USDT:USDT")
    now = 1700000000000
    stream._consume({"channel": "futures.trades", "event": "update", "time_ms": now,
                     "result": [{"price": "inf", "size": 1, "create_time_ms": now},
                                {"price": 100, "size": 1, "create_time_ms": now + 10}]})
    snapshot = stream.snapshot(now_ms=now)
    assert snapshot["recent_trades"] == snapshot["trade_flow_history"] == []


def test_peer_eof_invalidates_l2_before_reconnect(monkeypatch):
    import sys
    import threading
    from types import SimpleNamespace

    stream = GatePublicStream("BTC/USDT:USDT")
    stream.set_orderbook_snapshot({"nonce": 5, "bids": [[1, 2]], "asks": [[2, 1]]})
    closed = threading.Event()
    class Socket:
        def send(self, raw):
            pass
        def recv(self):
            return ""
        def close(self):
            closed.set()
    monkeypatch.setitem(sys.modules, "websocket", SimpleNamespace(
        create_connection=lambda *a, **kw: Socket(), WebSocketTimeoutException=TimeoutError))
    stream.start()
    try:
        assert closed.wait(1)
        assert stream.snapshot()["orderbook"] is None
    finally:
        stream.stop()



def test_snapshot_copies_trade_deque_before_iterating_outside_lock():
    from collections import deque

    class LockCheckingDeque(deque):
        def __init__(self, owner):
            super().__init__([{
                "timestamp_ms": 1700000000000,
                "price": 100.0,
                "size": 1.0,
                "side": "BUY",
            }])
            self.owner = owner

        def __iter__(self):
            assert self.owner._lock._is_owned(), "shared deque iterated without its lock"
            return super().__iter__()

    stream = GatePublicStream("BTC/USDT:USDT")
    stream._trades = LockCheckingDeque(stream)
    snapshot = stream.snapshot(now_ms=1700000001000)
    assert snapshot["trade_flow_history"]
