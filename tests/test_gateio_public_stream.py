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
